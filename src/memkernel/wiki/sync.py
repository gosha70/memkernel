# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""Export long-term memories to wiki pages and import wiki pages as memories.

Direction 1 — ``WikiExporter`` ("compile"): every long-term memory that has no
wiki page yet becomes a *draft* page in the matching section, with the page
sections the wiki schema requires. The exporter is deliberately LLM-free: it
produces a reviewable draft (the memory content in the primary section,
placeholders elsewhere) and leaves synthesis to the agent or curator, mirroring
the proposal → promote flow of ``code-copilot-team/scripts/wiki``.

Direction 2 — ``WikiImporter`` ("index"): every curated page becomes a
long-term memory (type by page_type) so ``recall`` can find it. Re-running the
importer is idempotent: unchanged pages dedup on content hash, changed pages
supersede their previous version.
"""

from __future__ import annotations

import contextlib
import logging
import os
import re
import subprocess
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from memkernel.core.models import (
    PAGE_KEY_TAG,
    PAGE_SHA_TAG,
    STORE_LOCK_WIKI_IMPORT,
    WIKI_ID_TAG,
    WIKI_PAGE_TAG,
    WIKI_PAGE_TYPE_TAG,
    WIKI_PATH_TAG,
    WIKI_TAG,
    WITHDRAWN_DELETED,
    WITHDRAWN_DEPRECATED,
    WITHDRAWN_SUPERSEDED,
    AmbiguousDedupError,
    MemoryTier,
    MemoryType,
    has_wiki_identity,
)
from memkernel.wiki.ledger import (
    ACTION_IMPORT,
    ACTION_SUPERSEDE,
    ACTION_WITHDRAW,
    ORIGIN_IMPORT,
    ORIGIN_REBUILT,
    STATE_APPLIED,
    STATE_FAILED,
    STATE_PENDING,
    LedgerEntry,
    LedgerMigrationError,
    SyncLedger,
    ledger_exists,
    migrate_ledger,
    wiki_key,
)
from memkernel.wiki.pages import WikiPage, parse_page, render_page, slugify
from memkernel.wiki.studio import (
    PATH_GATED,
    PATH_UNGATED,
    SUPERSEDED_STATE,
    WIKI_MODE_GOVERNED,
    WIKI_MODE_UNGATED,
    GatedPage,
    GateError,
    GateUncertainError,
    LintError,
    LintSummary,
    PageReview,
    gate_available,
    governed_preflight,
    lint_wiki,
    load_studio,
    propose_and_promote,
    read_wiki_id,
    review_pages,
    studio_installed,
    wiki_id,
)

if TYPE_CHECKING:
    from memkernel.core.models import Memory
    from memkernel.core.services import MemoryService

logger = logging.getLogger(__name__)

DEPRECATED_STATUS = "deprecated"
# Why a page was left untouched (memkernel-0-7-wiki-scope S4): the ``reason`` of an ``ambiguous`` report entry.
REASON_UNPROVEN = "legacy owner unproven"
REASON_SEVERAL = "several legacy candidates"
REASON_DUPLICATES = "duplicate records"
REASON_CHANGED = "candidate changed"
REASON_NOT_AMBIGUOUS = "not ambiguous"
CORRECTS_KEY = "corrects"  # memkernel's frontmatter key (wiki-studio ADR-0002 registers it, keeps it byte for byte)
_CORRECTS_TOKEN = re.compile(r"[A-Za-z0-9_-]+")
INDEX_FILE = "index.md"
LOG_FILE = "log.md"
DEFAULT_PROPOSALS_SUBDIR = Path(".memkernel") / "wiki-proposals"

# MemoryType -> (page_type, directory). CODE is not exported: code lives in the
# repo. DOCUMENT is not exported either: documents are sources, not wiki pages.
EXPORT_MAP: dict[MemoryType, tuple[str, str]] = {
    MemoryType.DECISION: ("decision", "decisions"),
    MemoryType.CONVENTION: ("concept", "concepts"),
    MemoryType.FACT: ("concept", "concepts"),
    MemoryType.PROCEDURE: ("workflow", "workflows"),
}

# page_type -> MemoryType for import. Pages without a mapping are skipped.
IMPORT_MAP: dict[str, MemoryType] = {
    "decision": MemoryType.DECISION,
    "concept": MemoryType.FACT,
    "overview": MemoryType.FACT,
    "glossary": MemoryType.FACT,
    "incident": MemoryType.FACT,
    "open-question": MemoryType.FACT,
    "workflow": MemoryType.PROCEDURE,
    "playbook": MemoryType.PROCEDURE,
}

# Required H2 sections per page type (first one receives the memory content).
PAGE_SECTIONS: dict[str, list[str]] = {
    "decision": ["Decision", "Context", "Alternatives considered", "Consequences"],
    "concept": ["Summary", "Key ideas", "Where this shows up", "Related"],
    "workflow": ["When to use this", "Steps", "Verification", "Related"],
}

PLACEHOLDER = "_Not recorded in memory — curate before marking this page stable._"
UNGATED_LINT_HINT = "MEMKERNEL_WIKI_MODE=ungated: wiki-studio is never loaded, so there is no lint"
UNGOVERNED_INDEX_REFUSAL = (
    "MEMKERNEL_WIKI_MODE=governed: update_index=False is refused, since pages without index entries cannot pass "
    "the gate and the direct writer is never used"
)
# The commit a page's ``path:`` source is grounded at (G4): wiki-studio's citation rule, read-only git, optional.
GIT_TIMEOUT_SECONDS = 2.0  # per call; after one timeout the export stops asking git
SOURCE_SHA_KEY = "sha"
MEMKERNEL_SHA256_KEY = "memkernel_sha256"


def _today() -> str:
    return datetime.now(UTC).date().isoformat()


@dataclass
class ExportReport:
    """Outcome of an export run.

    ``lint`` holds wiki-studio's lint and health results for the **whole wiki**
    as it is after the export (curated pages included), or ``None`` when the
    ``memkernel[wiki]`` extra is not installed or its lint pass failed; in the
    latter case ``lint_error`` says why. The written files are the same in
    every case.
    """

    written: list[str] = field(default_factory=list)
    skipped: int = 0
    lint: LintSummary | None = None
    lint_error: str | None = None
    gated: bool = False  # the pages went through wiki-studio's promote gate
    gate_error: str | None = None  # the gate rejected the export; no page was written, unless uncertain_outcome is set
    # From wiki-studio's receipt for a gated export (FR-005); None for the direct writer.
    proposal: str | None = None
    submission_digest: str | None = None
    archived_dir: str | None = None  # None on a promoted export means committed but not archived: archive_hint
    archive_hint: str | None = None
    receipt_error: str | None = None
    uncertain_outcome: str | None = None  # FR-009: pages may be on disk; compare the wiki with the receipt by hand
    mode: str = PATH_UNGATED  # the path that ran: gated (wiki-studio's gate) or ungated (G1)
    configured_mode: str = ""  # MEMKERNEL_WIKI_MODE
    remaining: int | None = 0  # eligible memories still without a page (G3); None when the outcome is uncertain


@dataclass
class ImportReport:
    """Outcome of an import run.

    ``governed`` is True when wiki-studio's review state decided what was imported (approved revisions only),
    False when wiki-studio is not installed and the page files were read directly (drafts included).
    ``not_approved`` lists the pages a governed import skipped, each with its review state and reason;
    ``import_error`` says why nothing was imported (an installed wiki-studio that is broken or too old).
    """

    imported: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)  # pages that cannot be imported (type, deprecated, unparsable)
    unchanged: list[str] = field(default_factory=list)  # approved pages whose revision is already the live memory
    governed: bool = False
    not_approved: list[dict[str, str]] = field(default_factory=list)
    corrections: list[dict[str, str]] = field(default_factory=list)  # {"page", "ref_id"} superseded by the page
    unresolved: list[dict[str, str]] = field(default_factory=list)  # {"page", "token", "reason"}
    invalid_corrects: list[dict[str, str]] = field(default_factory=list)  # {"page", "reason"}
    import_error: str | None = None
    # memkernel-0-7 (governed import only): memories taken out of the current answers and the sync ledger's state.
    withdrawn: list[dict[str, str]] = field(default_factory=list)  # {"path", "ref_id", "reason"}
    superseded: list[dict[str, str]] = field(default_factory=list)  # {"path", "ref_id", "by"}
    pending: list[dict[str, str]] = field(default_factory=list)  # {"path", "action", "detail"}
    sync_failed: list[dict[str, Any]] = field(default_factory=list)  # {"path", "action", "error", "attempts"}
    ledger_error: str | None = None
    # memkernel-0-7-wiki-scope S4: pages left untouched, {"path", "ref_ids", "reason"}.
    ambiguous: list[dict[str, Any]] = field(default_factory=list)
    mode: str = PATH_UNGATED  # the path that ran: gated (wiki-studio's review state) or ungated (G1)
    configured_mode: str = ""  # MEMKERNEL_WIKI_MODE


class WikiExporter:
    """Compile long-term memories into draft wiki pages under ``wiki_dir``."""

    def __init__(
        self,
        service: MemoryService,
        wiki_dir: Path,
        project_root: Path | None = None,
        proposals_dir: Path | None = None,
    ) -> None:
        self._service = service
        self._wiki_dir = Path(wiki_dir)
        # The root ``path:`` sources resolve against; memkernel's project root when the tool passes it.
        self._project_root = Path(project_root) if project_root is not None else self._wiki_dir.parent
        # An explicit proposals directory is a request for the gate (FR-006): its absence is then worth a warning.
        self._proposals_requested = proposals_dir is not None
        self._proposals_dir = (
            Path(proposals_dir) if proposals_dir is not None else self._project_root / DEFAULT_PROPOSALS_SUBDIR
        )

    def export(self, memories: list[Memory] | None = None, update_index: bool = True) -> ExportReport:
        """Write one page per exportable memory that is not already a wiki page.

        Memories that came from the wiki (tagged ``wiki``), chunk records, or
        retired memories (superseded or withdrawn) are skipped. Existing pages with
        the same slug are left untouched: the wiki, once written, is curated
        by humans/agents, not overwritten by the store. With the ``memkernel[wiki]``
        extra installed the report carries wiki-studio's lint and health findings
        for the whole wiki as it is after the export; a lint failure is reported
        in ``lint_error`` and never fails the export.
        """
        settings = self._service.settings
        report = ExportReport(configured_mode=settings.wiki_mode)
        governed_api = None
        if settings.wiki_mode == WIKI_MODE_GOVERNED:  # before any read of the wiki (G1)
            report.mode = PATH_GATED
            try:
                if not update_index:
                    raise GateError(UNGOVERNED_INDEX_REFUSAL)
                governed_api = governed_preflight(self._wiki_dir, self._project_root)
            except GateError as exc:  # before api.init: a refusal writes, reads and lints nothing
                report.gate_error = str(exc)
                report.remaining = None  # eligibility was never checked against the wiki
                logger.warning("wiki export to %s refused: %s", self._wiki_dir, exc)
                return report
        candidates = memories if memories is not None else self._service.list_memories(tier=MemoryTier.LONG_TERM)
        # G3: the most important first, then the oldest, then by ref_id, so a batch is deterministic
        candidates = sorted(candidates, key=lambda m: (-m.importance, m.timestamp, m.ref_id))
        planned: list[tuple[str, WikiPage]] = []
        for memory in candidates:
            mapping = EXPORT_MAP.get(memory.type)
            if mapping is None or WIKI_TAG in memory.tags or memory.retired() or memory.chunk_refs:
                report.skipped += 1
                continue
            page_type, directory = mapping
            page = self._page_for(memory, page_type)
            rel = f"{directory}/{page.slug}.md"
            if (self._wiki_dir / rel).exists() or any(r == rel for r, _ in planned):
                report.skipped += 1
                continue
            planned.append((rel, page))
        eligible = len(planned)
        if settings.wiki_export_batch > 0:
            planned = planned[: settings.wiki_export_batch]
        git = _Git(self._project_root)
        for _, page in planned:
            self._ground(page, git)

        api = None
        if settings.wiki_mode == WIKI_MODE_UNGATED:  # wiki-studio is never loaded (G1)
            pass
        elif settings.wiki_mode == WIKI_MODE_GOVERNED:
            api = governed_api if planned else None
        else:
            # Pages without index entries are orphans, which the gate rejects by design; update_index=False
            # therefore always takes the direct writer.
            report.mode = PATH_GATED if update_index and studio_installed() else PATH_UNGATED
            try:
                api = gate_available() if planned and update_index else None
            except GateError as exc:  # wiki-studio installed but broken: never fall back to unchecked writes
                report.gate_error = str(exc)
                report.skipped += len(planned)
                planned = []
            if self._proposals_requested and api is None and report.gate_error is None:
                if planned and not update_index:
                    logger.warning(
                        "wiki gate requested (proposals directory set) but update_index=False bypasses it: "
                        "pages without index entries cannot pass the gate; writing directly"
                    )
                else:
                    # logs once that the requested gate is unavailable; a broken installation with nothing
                    # to write is reported by the lint pass below
                    with contextlib.suppress(LintError):
                        load_studio(require_studio=True)
        if api is not None:
            self._export_gated(api, planned, report)
        elif report.gate_error is None:
            for rel, page in planned:
                target = self._wiki_dir / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(render_page(page), encoding="utf-8")
                report.written.append(rel)
                if update_index:
                    self._append_index(rel, page)
                    self._append_log(page, "created")
        report.remaining = None if report.uncertain_outcome is not None else eligible - len(report.written)
        if settings.wiki_mode != WIKI_MODE_UNGATED:
            try:
                report.lint = lint_wiki(self._wiki_dir, self._project_root)
            except LintError as exc:
                report.lint_error = str(exc)
        return report

    def _export_gated(self, api: object, planned: list[tuple[str, WikiPage]], report: ExportReport) -> None:
        """Every page through propose + promote; the gate scaffolds a missing index.md and log.md first."""
        index_path = self._wiki_dir / INDEX_FILE
        try:
            index_text = index_path.read_text(encoding="utf-8") if index_path.exists() else ""
        except (OSError, UnicodeDecodeError) as exc:  # reported like every other gate failure, nothing written
            report.gate_error = f"could not read {INDEX_FILE}: {exc}"
            report.skipped += len(planned)
            logger.warning("wiki export to %s failed: %s", self._wiki_dir, report.gate_error)
            return
        pages = [
            GatedPage(
                path=rel,
                content=render_page(page),
                # same rule as the direct writer: no second index entry for a page already linked
                index_line=self._index_line(rel, page) if f"]({rel})" not in index_text else None,
                log_line=self._log_line(page, "created"),
            )
            for rel, page in planned
        ]
        name = f"memkernel-export-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
        try:
            result = propose_and_promote(api, pages, self._wiki_dir, self._project_root, self._proposals_dir, name)
        except GateUncertainError as exc:  # neither committed nor rolled back: never reported as written
            report.gate_error = str(exc)
            report.skipped += len(pages)
            report.proposal = exc.proposal
            report.uncertain_outcome = exc.uncertain_outcome
            report.receipt_error = exc.receipt_error
            return
        except GateError as exc:  # wiki-studio rolled back its own writes; nothing here to restore
            report.gate_error = str(exc)
            report.skipped += len(pages)
            return
        report.gated = True
        report.written.extend(page.path for page in pages)
        report.proposal = result.proposal
        report.submission_digest = result.submission_digest
        report.archived_dir = result.archived_dir
        report.archive_hint = result.archive_hint
        report.receipt_error = result.receipt_error

    @staticmethod
    def _index_line(rel: str, page: WikiPage) -> str:
        return f"- [{page.title}]({rel}) — draft compiled from memkernel ({page.extra.get('memory_type', '')})."

    @staticmethod
    def _log_line(page: WikiPage, verb: str) -> str:
        ref = page.extra.get("memkernel_ref", "")
        return f"- {_today()} — {verb} `{page.slug}` ({page.page_type}): compiled from memkernel {ref}"

    def _page_for(self, memory: Memory, page_type: str) -> WikiPage:
        title = memory.content.strip().splitlines()[0][:80] if memory.content.strip() else memory.ref_id
        slug = slugify(title)
        sections = PAGE_SECTIONS[page_type]
        body_lines = [f"# {title}", ""]
        for i, heading in enumerate(sections):
            body_lines.append(f"## {heading}")
            body_lines.append("")
            body_lines.append(memory.content.strip() if i == 0 else PLACEHOLDER)
            body_lines.append("")
        sources: list[dict[str, str]] = [
            {"url": f"memkernel://{memory.project_id}/{memory.ref_id}", "retrieved": _today()}
        ]
        if memory.source:
            sources.append({"path": memory.source})
        return WikiPage(
            page_type=page_type,
            slug=slug,
            title=title,
            status="draft",
            last_reviewed=_today(),
            sources=sources,
            body="\n".join(body_lines),
            extra={
                "memkernel_ref": memory.ref_id,
                "memory_type": memory.type.value,
                MEMKERNEL_SHA256_KEY: memory.content_hash,
            },
        )

    @staticmethod
    def _ground(page: WikiPage, git: _Git) -> None:
        """G4: a ``path:`` source of a file git tracks, unmodified, gains the commit it is grounded at."""
        for source in page.sources:
            path = source.get("path")
            if path:
                sha = git.source_commit(path)
                if sha is not None:
                    source[SOURCE_SHA_KEY] = sha

    def _append_index(self, rel: str, page: WikiPage) -> None:
        index = self._wiki_dir / INDEX_FILE
        if not index.exists():
            index.write_text(_index_scaffold(), encoding="utf-8")
        text = index.read_text(encoding="utf-8")
        if f"]({rel})" in text:
            return
        if not text.endswith("\n"):
            text += "\n"
        index.write_text(text + self._index_line(rel, page) + "\n", encoding="utf-8")

    def _append_log(self, page: WikiPage, verb: str) -> None:
        log = self._wiki_dir / LOG_FILE
        if not log.exists():
            log.write_text(_log_scaffold(), encoding="utf-8")
        with log.open("a", encoding="utf-8") as fh:
            fh.write(self._log_line(page, verb) + "\n")


class _Git:
    """Read-only git in one project root for one export; after a timeout it is not asked again (G4)."""

    def __init__(self, project_root: Path) -> None:
        self._given = project_root
        self._root = project_root.resolve()
        self._timed_out = False

    def run(self, *args: str) -> str | None:
        """``git <args>`` with pathspecs taken literally; None when git is missing, fails or timed out."""
        if self._timed_out:
            return None
        try:
            done = subprocess.run(  # noqa: S603 — fixed argv, no shell
                ["git", "--literal-pathspecs", "-C", str(self._root), *args],  # noqa: S607 — git from PATH, optional
                capture_output=True,
                text=True,
                timeout=GIT_TIMEOUT_SECONDS,
                check=False,
            )
        except subprocess.TimeoutExpired:
            self._timed_out = True
            logger.warning(
                "git did not answer within %ss in %s; exported pages get no sha:", GIT_TIMEOUT_SECONDS, self._root
            )
            return None
        except (OSError, subprocess.SubprocessError):
            return None
        return done.stdout if done.returncode == 0 else None

    def _lexical(self, source: str) -> str | None:
        """``source`` relative to the project root without following symlinks; None when it leaves the root."""
        path = os.path.normpath(source)
        if os.path.isabs(path):
            for base in (os.path.abspath(self._given), str(self._root)):
                try:
                    rel = os.path.relpath(path, base)
                except ValueError:  # another drive
                    continue
                if not rel.startswith(os.pardir):
                    path = rel
                    break
            else:
                return None
        if path in (os.curdir, "") or path.startswith(os.pardir) or os.path.isabs(path):
            return None
        return Path(path).as_posix()

    def source_commit(self, source: str) -> str | None:
        """The commit ``source`` is grounded at, as wiki-studio's citation rules define it (``git log -1
        --format=%h``), only when the project's ``git ls-files`` lists exactly that path and ``git status`` shows no
        change to it. A file outside the project, untracked, modified or staged, inside a submodule, or no git:
        None."""
        rel_posix = self._lexical(source)
        if rel_posix is None:
            return None
        try:  # containment on the resolved path; git is asked about the source's own path (a symlink is its own file)
            (self._root / rel_posix).resolve().relative_to(self._root)
        except (OSError, ValueError):
            return None
        listed = self.run("ls-files", "-z", "--", rel_posix)
        if listed is None or listed.split("\0")[:-1] != [rel_posix]:
            return None
        if self.run("status", "--porcelain", "--", rel_posix) != "":
            return None
        sha = (self.run("log", "-1", "--format=%h", "--", rel_posix) or "").strip()
        return sha or None


def _index_scaffold() -> str:
    return (
        "---\npage_type: index\nslug: index\ntitle: Wiki Index\nstatus: draft\n"
        f"last_reviewed: {_today()}\n---\n\n# Wiki Index\n\n## Compiled from memkernel\n\n"
    )


def _log_scaffold() -> str:
    return (
        "---\npage_type: log\nslug: log\ntitle: Wiki Edit Log\nstatus: draft\n"
        f"last_reviewed: {_today()}\n---\n\n# Wiki Edit Log\n\n## Entries\n\n"
    )


class WikiImporter:
    """Index wiki pages as long-term memories: approved revisions only when wiki-studio is installed.

    Every memory the import writes or finds current carries the wiki's identity (memkernel-0-7-wiki-scope S1):
    ``wiki-path:<hash>`` and, with a manifest, ``wiki-id:<uuid>``. A page's previous memory, its corrections, its
    supersession and its deprecation are this wiki's only; a legacy memory (0.6, no identity tag) joins it only
    on the owner's word (``adopt_legacy``, ``adopt_pages``).
    """

    def __init__(self, service: MemoryService, wiki_dir: Path, project_root: Path | None = None) -> None:
        self._service = service
        self._wiki_dir = Path(wiki_dir)
        self._project_root = Path(project_root) if project_root is not None else self._wiki_dir.parent
        self._identity = WikiIdentity("", None)
        self._adopt_legacy = False
        self._adopt_pages: dict[str, str] = {}
        self._named: set[str] = set()

    def import_pages(
        self,
        session_id: str | None = None,
        *,
        adopt_legacy: bool = False,
        adopt_pages: list[dict[str, str]] | None = None,
        adopt_manifest: bool = False,
    ) -> ImportReport:
        """Retain each importable page; return what was imported, skipped and why (memkernel-0-6 FR-010-FR-016).

        ``adopt_legacy`` adopts each page's sole legacy memory, ``adopt_pages`` (``{"path", "ref_id"}`` entries
        from an ``ambiguous`` report) exactly the records named, and ``adopt_manifest`` the memories of a wiki
        that gained a manifest: the owner's assertions, per call (memkernel-0-7-wiki-scope S4, S6).
        """
        configured = self._service.settings.wiki_mode
        report = ImportReport(configured_mode=configured)
        identity: str | None = None
        try:
            if configured == WIKI_MODE_UNGATED:  # wiki-studio is never loaded (G1)
                api = None
            else:
                report.mode = PATH_GATED if configured == WIKI_MODE_GOVERNED or studio_installed() else PATH_UNGATED
                if configured == WIKI_MODE_GOVERNED:
                    api = governed_preflight(self._wiki_dir, self._project_root)
                else:
                    api = gate_available()
            reviews = review_pages(api, self._wiki_dir, self._project_root) if api is not None else None
            identity = (
                wiki_id(api, self._wiki_dir, self._project_root) if api is not None else read_wiki_id(self._wiki_dir)
            )
        except GateError as exc:  # installed but broken, too old or failing: never fall back to the ungoverned path
            report.import_error = str(exc)
            logger.warning("wiki import from %s refused: %s", self._wiki_dir, exc)
            return report
        self._identity = WikiIdentity(wiki_key(None, self._wiki_dir, self._project_root), identity)
        self._adopt_legacy = adopt_legacy
        self._adopt_pages = {entry["path"]: entry["ref_id"] for entry in adopt_pages or []}
        self._named = set()
        settings = self._service.settings
        persisted = bool(settings.chroma_persist_path.strip())
        project = self._service.project_id
        # One import at a time per store (wiki-scope S8): the checks below and the writes they allow are one step.
        with self._service.exclusive(STORE_LOCK_WIKI_IMPORT):
            live = self._live()
            path_ledger = reviews is not None and ledger_exists(
                settings.state_dir, persisted, project, self._identity.path_hash
            )
            error = self._identity_error(live, adopt_manifest, path_ledger)
            if error is not None:
                report.import_error = error
                logger.warning("wiki import from %s refused: %s", self._wiki_dir, error)
                return report
            if reviews is not None and identity is not None and adopt_manifest:
                try:
                    migrate_ledger(settings.state_dir, persisted, project, self._identity.path_hash, identity)
                except LedgerMigrationError as exc:
                    report.import_error = str(exc)
                    return report
            self._retag(live, adopt_manifest)
            live = self._live()
            if reviews is None:
                self._import_files(report, live, session_id)
            else:
                report.governed = True
                ledger = SyncLedger.for_wiki(
                    settings.state_dir, persisted, project, identity, self._wiki_dir, self._project_root
                )
                with ledger.run():
                    if ledger.error is not None:
                        report.ledger_error = ledger.error
                        self._rebuild(ledger, live)
                    self._import_reviewed(reviews, report, live, session_id, ledger)
                    self._withdraw(reviews, report, ledger, session_id)
            for path in sorted(set(self._adopt_pages) - self._named):
                self._ambiguous(report, path, [self._adopt_pages[path]], REASON_NOT_AMBIGUOUS)
        return report

    def _live(self) -> list[Memory]:
        return [m for m in self._service.list_memories(tier=MemoryTier.LONG_TERM) if WIKI_TAG in m.tags]

    def _identity_error(self, live: list[Memory], adopt_manifest: bool, path_ledger: bool) -> str | None:
        """The identity checks, before any write (wiki-scope S6): a conflicting identity at this path, and a
        manifest added without the owner's ``adopt_manifest``."""
        ident = self._identity
        foreign = sorted(
            {
                tag
                for m in live
                if ident.path_tag in m.tags
                for tag in m.tags
                if tag.startswith(WIKI_ID_TAG) and tag != ident.id_tag
            }
        )
        if foreign:
            return (
                f"memories at this wiki's path belong to another wiki ({', '.join(foreign)}): its manifest was "
                "removed or replaced, or another directory now stands here. If the manifest was removed, restore "
                "it; if it was replaced (a re-init), restore the earlier one; if that wiki moved, import it from "
                "its new location first; if it is gone for good, forget its memories"
            )
        if ident.wiki_id is None or adopt_manifest:
            return None
        path_only = [m.ref_id for m in live if ident.path_tag in m.tags and not _ids(m)]
        if path_only or path_ledger:
            return (
                f"this wiki gained a manifest (wiki_id {ident.wiki_id}) and its earlier memories carry only its "
                "path: import with adopt_manifest=true if this directory is the same wiki it was before"
            )
        return None

    def _retag(self, live: list[Memory], adopt_manifest: bool) -> None:
        """Before any page write: a moved wiki's memories take its current path; with ``adopt_manifest``, the
        path-only memories at this path take its ``wiki_id`` (wiki-scope S6). Per record and idempotent."""
        ident = self._identity
        if ident.wiki_id is None:
            return
        for memory in live:
            moved = ident.id_tag in memory.tags and [t for t in memory.tags if t.startswith(WIKI_PATH_TAG)] != [
                ident.path_tag
            ]
            adopted = adopt_manifest and ident.path_tag in memory.tags and not _ids(memory)
            if moved or adopted:
                self._service.set_wiki_identity(memory.ref_id, wiki_path=ident.path_hash, wiki_id=ident.wiki_id)

    def _import_files(self, report: ImportReport, live: list[Memory], session_id: str | None) -> None:
        """Without wiki-studio: every page file, drafts included (ungoverned, as before 0.6)."""
        for path in sorted(self._wiki_dir.rglob("*.md")):
            rel = path.relative_to(self._wiki_dir).as_posix()
            if rel.startswith(("schema/", "scripts/", ".")):
                continue
            page = parse_page(path.read_text(encoding="utf-8"))
            self._retain_page(rel, page, None, live, session_id, report)

    def _import_reviewed(
        self,
        reviews: list[PageReview],
        report: ImportReport,
        live: list[Memory],
        session_id: str | None,
        ledger: SyncLedger,
    ) -> None:
        """Import every approved page, those with an unfinished ledger entry first (memkernel-0-7 FR-004)."""
        retry = {e.path for e in ledger.unfinished()}
        for review in sorted(reviews, key=lambda r: (r.path not in retry, r.path)):
            if review.text is None:
                report.not_approved.append({"path": review.path, "state": review.state, "reason": review.reason})
                continue
            page = parse_page(review.text)
            if page is not None and page.status == DEPRECATED_STATUS:
                continue  # withdrawn in _withdraw once the deprecated revision is approved (D5)
            prior = ledger.entries.get(review.page_key)
            entry = LedgerEntry(review.page_key, review.path, STATE_PENDING, ACTION_IMPORT, sha256=review.sha256 or "")
            ledger.mark(entry, STATE_PENDING)
            imported_before = len(report.imported)
            try:
                ref_id = self._retain_page(review.path, page, review, live, session_id, report)
                if ref_id is not None and page is not None:
                    self._reconcile(review.path, page, review, ref_id, report)
            except Exception as exc:  # one page's failure is recorded and retried; the run goes on
                self._failed(ledger, entry, prior, exc, report)
                continue
            if ref_id is None:  # skipped or ambiguous: nothing in the store to track
                self._restore(ledger, entry.page_key, prior)
                continue
            entry.ref_id = ref_id
            if len(report.imported) == imported_before:  # already current: adopt it, keeping a prior entry's origin
                entry.origin = prior.origin if prior is not None and prior.ref_id == ref_id else ORIGIN_REBUILT
            ledger.mark(entry, STATE_APPLIED)

    def _withdraw(
        self, reviews: list[PageReview], report: ImportReport, ledger: SyncLedger, session_id: str | None
    ) -> None:
        """memkernel-0-7 FR-005: deletion (D3), supersession (D4) and deprecation (D5), in that order."""
        live = self._live()
        listed_keys = {r.page_key for r in reviews}
        listed_paths = {r.path for r in reviews}
        by_path = {r.path: r for r in reviews}
        history = [
            m
            for m in self._service.list_memories(tier=MemoryTier.LONG_TERM, include_superseded=True)
            if WIKI_TAG in m.tags and m.withdrawn_reason == WITHDRAWN_DEPRECATED and self._identity.owns(m)
        ]
        for entry in list(ledger.entries.values()):  # D3: only memories this wiki's ledger recorded
            deletion_retry = entry.action == ACTION_WITHDRAW and entry.detail == WITHDRAWN_DELETED
            recorded = entry.action == ACTION_IMPORT and entry.state == STATE_APPLIED and entry.origin == ORIGIN_IMPORT
            if not (recorded or (deletion_retry and entry.state != STATE_APPLIED)) or not entry.ref_id:
                continue
            if entry.page_key in listed_keys or entry.path in listed_paths or (self._wiki_dir / entry.path).exists():
                continue
            self._apply_withdrawal(ledger, report, entry, entry.ref_id, WITHDRAWN_DELETED)
        for review in reviews:  # D4
            if review.superseded_by is not None or review.state == SUPERSEDED_STATE:
                self._supersede_page(review, by_path, live, report, ledger)
        for review in reviews:  # D5: the deprecated revision is approved
            page = parse_page(review.text) if review.text is not None else None
            if page is None or page.status != DEPRECATED_STATUS:
                continue
            resolved, previous = self._resolve(review.path, review, live, report)
            if not resolved:
                continue  # ambiguous: no store write, no ledger mark (S3)
            if previous is None:
                if not _lookup(review.path, review, history):  # never imported: nothing to withdraw
                    report.skipped.append(review.path)
                continue  # already withdrawn as deprecated (FR-006): neither withdrawn again nor skipped
            entry = LedgerEntry(
                review.page_key, review.path, STATE_PENDING, ACTION_WITHDRAW, detail=WITHDRAWN_DEPRECATED
            )
            self._apply_withdrawal(ledger, report, entry, previous.ref_id, WITHDRAWN_DEPRECATED)

    def _supersede_page(
        self,
        review: PageReview,
        by_path: dict[str, PageReview],
        live: list[Memory],
        report: ImportReport,
        ledger: SyncLedger,
    ) -> None:
        """D4: supersede by the successor's memory when it exists; else withdraw and wait for it, reported."""
        prior = ledger.entries.get(review.page_key)
        resolved, old = self._resolve(review.path, review, live, report)
        if not resolved:
            return  # ambiguous predecessor: no store write, no ledger mark (S3)
        old_ref = old.ref_id if old is not None else (prior.ref_id if prior is not None else "")
        if not old_ref:
            return  # never imported: nothing in the store to supersede
        successor = review.superseded_by or ""
        succ_review = by_path.get(successor)
        succ = None
        if succ_review is not None:
            resolved, succ = self._resolve(successor, succ_review, live, report)
            if not resolved:
                return  # ambiguous successor: no store write, no ledger mark (S3)
        entry = LedgerEntry(review.page_key, review.path, STATE_PENDING, ACTION_SUPERSEDE, ref_id=old_ref)
        entry.detail = successor
        entry.attempts = prior.attempts if prior is not None else 0
        try:
            if succ is None:
                if old is not None:
                    self._service.withdraw(old_ref, WITHDRAWN_SUPERSEDED)
                why = "not in the wiki's listing" if succ_review is None else f"no memory yet ({succ_review.state})"
                ledger.mark(entry, STATE_PENDING)
                report.pending.append(
                    {"path": review.path, "action": ACTION_SUPERSEDE, "detail": f"successor {successor}: {why}"}
                )
                return
            current = self._service.get(old_ref, touch=False)
            if current is not None and current.superseded_by != succ.ref_id:
                self._service.supersede(old_ref, succ.ref_id)
                report.superseded.append({"path": review.path, "ref_id": old_ref, "by": succ.ref_id})
        except (ValueError, OSError) as exc:
            self._failed(ledger, entry, prior, exc, report)
            return
        ledger.mark(entry, STATE_APPLIED)

    def _apply_withdrawal(
        self, ledger: SyncLedger, report: ImportReport, entry: LedgerEntry, ref_id: str, reason: str
    ) -> None:
        prior = ledger.entries.get(entry.page_key)
        entry.action, entry.detail, entry.ref_id = ACTION_WITHDRAW, reason, ref_id
        entry.attempts = prior.attempts if prior is not None else 0
        ledger.mark(entry, STATE_PENDING)
        try:
            changed = self._service.withdraw(ref_id, reason)
        except (ValueError, OSError) as exc:
            self._failed(ledger, entry, prior, exc, report)
            return
        ledger.mark(entry, STATE_APPLIED)
        if changed:
            report.withdrawn.append({"path": entry.path, "ref_id": ref_id, "reason": reason})

    @staticmethod
    def _failed(
        ledger: SyncLedger, entry: LedgerEntry, prior: LedgerEntry | None, exc: Exception, report: ImportReport
    ) -> None:
        entry.attempts = prior.attempts if prior is not None else entry.attempts
        ledger.mark(entry, STATE_FAILED, str(exc))
        logger.warning("wiki import: %s of %s failed: %s", entry.action, entry.path, exc)
        report.sync_failed.append(
            {"path": entry.path, "action": entry.action, "error": str(exc), "attempts": entry.attempts}
        )

    @staticmethod
    def _restore(ledger: SyncLedger, page_key: str, prior: LedgerEntry | None) -> None:
        if prior is None:
            ledger.entries.pop(page_key, None)
        else:
            ledger.entries[page_key] = prior

    def _rebuild(self, ledger: SyncLedger, live: list[Memory]) -> None:
        """A corrupt ledger is rebuilt from this wiki's memories' page_key tags (wiki-scope S7), with origin
        ``rebuilt``: such entries never make a memory eligible for deletion (D3), which needs proof an import run
        wrote it. Legacy memories and other wikis' are never used."""
        for memory in live:
            if not self._identity.owns(memory):
                continue
            keys = [_tag_unsafe(t[len(PAGE_KEY_TAG) :]) for t in memory.tags if t.startswith(PAGE_KEY_TAG)]
            if len(keys) != 1:
                continue
            entry = LedgerEntry(keys[0], memory.source, STATE_APPLIED, ACTION_IMPORT, ref_id=memory.ref_id)
            entry.origin = ORIGIN_REBUILT
            ledger.mark(entry, STATE_APPLIED)

    def _reconcile(self, rel: str, page: WikiPage, review: PageReview, ref_id: str, report: ImportReport) -> None:
        """FR-015: supersede the originating memories an approved page's ``corrects`` names by the page's memory."""
        raw = page.extra.get(CORRECTS_KEY)
        if raw is None:
            return
        try:
            tokens = parse_corrects(raw)
        except ValueError as exc:
            report.invalid_corrects.append({"page": rel, "reason": str(exc)})
            return
        for token in tokens:
            target = self._service.get(token, touch=False)
            if target is None:
                reason = "not a memory in this store"
            elif WIKI_TAG in target.tags:
                reason = "a memory imported from the wiki: correct the page instead"
            elif target.superseded_by and self._is_this_pages(target.superseded_by, rel, review):
                # Corrected by this page (this or an earlier revision): still in effect. The idempotent call
                # completes a mark an earlier import left partial (owned chunks without the marker).
                self._service.supersede(token, target.superseded_by)
                continue
            else:
                try:
                    if self._service.supersede(token, ref_id):
                        report.corrections.append({"page": rel, "ref_id": token})
                    continue
                except ValueError as exc:
                    reason = str(exc)
            report.unresolved.append({"page": rel, "token": token, "reason": reason})

    def _retain_page(
        self,
        rel: str,
        page: WikiPage | None,
        review: PageReview | None,
        live: list[Memory],
        session_id: str | None,
        report: ImportReport,
    ) -> str | None:
        """Retain one page; return its live memory's ref_id (new, or already current), or None when skipped or
        ambiguous (nothing written)."""
        memory_type = IMPORT_MAP.get(page.page_type) if page else None
        if page is None or memory_type is None or page.status == DEPRECATED_STATUS:
            report.skipped.append(rel)
            return None
        resolved, previous = self._resolve(rel, review, live, report)  # before the early return below (S3, S5)
        if not resolved:
            return None
        content = f"{page.title}\n\n{page.body}".strip()
        tags = [WIKI_TAG, f"{WIKI_PAGE_TAG}{page.slug}", f"{WIKI_PAGE_TYPE_TAG}{page.page_type}"]
        if review is not None:
            sha_tag = f"{PAGE_SHA_TAG}{review.sha256}"
            tags += [f"{PAGE_KEY_TAG}{_tag_safe(review.page_key)}", sha_tag]
            if previous is not None and sha_tag in previous.tags:
                # This approved revision is already the page's live memory. Its corrections are still reconciled
                # (idempotent), so a reference that resolves only later, or one a failed import left, takes effect.
                report.unchanged.append(rel)
                return previous.ref_id
            # A revision that changes only frontmatter keeps the same content, so retain dedups and merges the new
            # tags into the existing record: the record then carries one page_sha tag per such revision.
        # A page renamed under its page_id (G5) is found by key at its old path: its new record supersedes it.
        changed = previous is not None and (previous.content != content or previous.source != rel)
        supersedes = previous.ref_id if previous is not None and changed else None
        try:
            ref_id = self._service.retain(
                content=content,
                type=memory_type,
                session_id=session_id,
                source=rel,
                importance=0.9 if page.status == "stable" else 0.7,
                tags=tags,
                supersedes=supersedes,
                dedup_source=True,  # FR-012: one memory per page, never merged with identical text from elsewhere
                dedup_owner=self._identity.owns,  # S2: only this wiki's record is a dedup hit
                wiki_identity=(self._identity.path_hash, self._identity.wiki_id),
            )
        except AmbiguousDedupError as exc:
            self._ambiguous(report, rel, exc.ref_ids, REASON_DUPLICATES)
            return None
        report.imported.append(rel)
        return ref_id

    def _resolve(
        self, rel: str, review: PageReview | None, live: list[Memory], report: ImportReport
    ) -> tuple[bool, Memory | None]:
        """The page's previous memory (wiki-scope S3, S4): ``(False, None)`` when the page is ambiguous (reported;
        nothing may be written for it), else ``(True, memory or None)``.

        This wiki's own memories first, by page key, else by path; an interrupted supersession among them is
        completed from the replacement's ``supersedes``; two or more left are ``duplicate records``. Only when
        the wiki has none are legacy memories consulted, and one is adopted only on the owner's word.
        """
        named = self._adopt_pages.get(rel)
        if named is not None:
            self._named.add(rel)
        owned = self._recover(_lookup(rel, review, [m for m in live if self._identity.owns(m)]), live)
        if len(owned) > 1:
            self._ambiguous(report, rel, [m.ref_id for m in owned], REASON_DUPLICATES)
            return False, None
        legacy = [] if owned else _lookup(rel, review, [m for m in live if not has_wiki_identity(m.tags)], union=True)
        if named is not None and not legacy:
            if not owned and any(m.ref_id == named for m in _lookup(rel, review, live, union=True)):
                # The named record is still at this page but now another wiki's (adopted meanwhile): S8.
                self._ambiguous(report, rel, [named], REASON_CHANGED)
                return False, None
            self._ambiguous(report, rel, [named], REASON_NOT_AMBIGUOUS)
        if owned or not legacy:
            return True, owned[0] if owned else None
        if len(legacy) > 1:
            self._ambiguous(report, rel, [m.ref_id for m in legacy], REASON_SEVERAL)
            return False, None
        (candidate,) = legacy
        if named is not None and named != candidate.ref_id:
            self._ambiguous(report, rel, [candidate.ref_id], REASON_CHANGED)
            return False, None
        if named is None and not self._adopt_legacy:
            self._ambiguous(report, rel, [candidate.ref_id], REASON_UNPROVEN)
            return False, None
        self._service.set_wiki_identity(
            candidate.ref_id, wiki_path=self._identity.path_hash, wiki_id=self._identity.wiki_id
        )
        adopted = self._service.get(candidate.ref_id, touch=False)
        if adopted is None:  # forgotten meanwhile: treated as never imported
            return True, None
        live[live.index(candidate)] = adopted
        return True, adopted

    def _recover(self, candidates: list[Memory], live: list[Memory]) -> list[Memory]:
        """Complete an interrupted supersession (wiki-scope S3): a candidate whose ``supersedes`` names another
        live candidate is that one's replacement, so the predecessor is marked and dropped."""
        remaining = list(candidates)
        for replacement in candidates:
            predecessor = next((m for m in remaining if m.ref_id == replacement.supersedes), None)
            if predecessor is None or replacement not in remaining:
                continue
            self._service.supersede(predecessor.ref_id, replacement.ref_id)
            remaining.remove(predecessor)
            live.remove(predecessor)
        return remaining

    @staticmethod
    def _ambiguous(report: ImportReport, path: str, ref_ids: list[str], reason: str) -> None:
        entry = {"path": path, "ref_ids": sorted(ref_ids), "reason": reason}
        if entry not in report.ambiguous:
            report.ambiguous.append(entry)

    def _is_this_pages(self, ref_id: str, rel: str, review: PageReview) -> bool:
        """Whether ``ref_id`` is a memory this wiki imported from this page (any revision; wiki-scope S3)."""
        memory = self._service.get(ref_id, touch=False)
        key_tag = f"{PAGE_KEY_TAG}{_tag_safe(review.page_key)}"
        return memory is not None and self._identity.owns(memory) and (key_tag in memory.tags or memory.source == rel)


@dataclass(frozen=True)
class WikiIdentity:
    """A wiki's identity (memkernel-0-7-wiki-scope S1): its path hash and, with a manifest, its ``wiki_id``."""

    path_hash: str
    wiki_id: str | None

    @property
    def path_tag(self) -> str:
        return f"{WIKI_PATH_TAG}{self.path_hash}"

    @property
    def id_tag(self) -> str | None:
        return f"{WIKI_ID_TAG}{self.wiki_id}" if self.wiki_id else None

    def owns(self, memory: Memory) -> bool:
        """Membership: this wiki's ``wiki-id:``; or path-only at this path while the wiki has no manifest."""
        ids = _ids(memory)
        if ids:
            return self.id_tag is not None and ids == [self.id_tag]
        return self.wiki_id is None and self.path_tag in memory.tags


def _ids(memory: Memory) -> list[str]:
    return [tag for tag in memory.tags if tag.startswith(WIKI_ID_TAG)]


def _lookup(rel: str, review: PageReview | None, memories: list[Memory], *, union: bool = False) -> list[Memory]:
    """A page's memories among ``memories``: by page key, else by its wiki-relative path (never by slug).

    The path fallback also covers a page whose key changed (a curator added a ``page_id``) and an edit read
    without wiki-studio after a governed import. A record carrying several page keys (two pages merged by the
    unscoped dedup before FR-012's amendment) belongs to the page whose path is its ``source``. With ``union``,
    key and path matches together (the legacy candidates of S4).
    """
    by_key: list[Memory] = []
    if review is not None:
        key_tag = f"{PAGE_KEY_TAG}{_tag_safe(review.page_key)}"
        by_key = [m for m in memories if key_tag in m.tags and (m.source == rel or not _shared(m))]
        if by_key and not union:
            return by_key
    by_path = [m for m in memories if m.source == rel]
    return list({m.ref_id: m for m in [*by_key, *by_path]}.values())


def _shared(memory: Memory) -> bool:
    """Whether ``memory`` carries more than one page key: two pages merged into one record before FR-012's fix."""
    return sum(tag.startswith(PAGE_KEY_TAG) for tag in memory.tags) > 1


def _tag_safe(value: str) -> str:
    """Tags are stored comma-separated: a comma in a page key would split it into two tags."""
    return value.replace("%", "%25").replace(",", "%2C")


def _tag_unsafe(value: str) -> str:
    """The page key a ``_tag_safe`` tag holds."""
    return value.replace("%2C", ",").replace("%25", "%")


def parse_corrects(value: str) -> list[str]:
    """The ``corrects`` grammar (memkernel-0-6 FR-014): one line, a comma-separated list of tokens, each of letters,
    digits, ``-`` and ``_``, with optional whitespace around commas. Raises ``ValueError`` naming what is wrong."""
    if "\n" in value or "\r" in value:
        raise ValueError("corrects must be one line")
    if not value.strip():
        raise ValueError("corrects is empty")
    tokens = [part.strip() for part in value.split(",")]
    for token in tokens:
        if not token:
            raise ValueError("corrects has an empty token")
        if not _CORRECTS_TOKEN.fullmatch(token):
            raise ValueError(f"corrects token {token!r} has a character other than letters, digits, '-' or '_'")
    return tokens

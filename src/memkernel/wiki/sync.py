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
import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from memkernel.core.models import MemoryTier, MemoryType
from memkernel.wiki.pages import WikiPage, parse_page, render_page, slugify
from memkernel.wiki.studio import (
    GatedPage,
    GateError,
    LintError,
    LintSummary,
    PageReview,
    gate_available,
    lint_wiki,
    load_studio,
    propose_and_promote,
    review_pages,
)

if TYPE_CHECKING:
    from memkernel.core.models import Memory
    from memkernel.core.services import MemoryService

logger = logging.getLogger(__name__)

WIKI_TAG = "wiki"
PAGE_KEY_TAG = "page_key:"
PAGE_SHA_TAG = "page_sha:"
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
    gate_error: str | None = None  # the gate rejected the export; no page was written
    # From wiki-studio's receipt for a gated export (FR-005); None for the direct writer.
    proposal: str | None = None
    submission_digest: str | None = None
    archived_dir: str | None = None  # None on a promoted export means committed but not archived: archive_hint
    archive_hint: str | None = None
    receipt_error: str | None = None


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
        memories a newer memory supersedes (``superseded_by`` set) are skipped. Existing pages with
        the same slug are left untouched: the wiki, once written, is curated
        by humans/agents, not overwritten by the store. With the ``memkernel[wiki]``
        extra installed the report carries wiki-studio's lint and health findings
        for the whole wiki as it is after the export; a lint failure is reported
        in ``lint_error`` and never fails the export.
        """
        report = ExportReport()
        candidates = memories if memories is not None else self._service.list_memories(tier=MemoryTier.LONG_TERM)
        planned: list[tuple[str, WikiPage]] = []
        for memory in candidates:
            mapping = EXPORT_MAP.get(memory.type)
            if mapping is None or WIKI_TAG in memory.tags or memory.superseded_by or memory.chunk_refs:
                report.skipped += 1
                continue
            page_type, directory = mapping
            page = self._page_for(memory, page_type)
            rel = f"{directory}/{page.slug}.md"
            if (self._wiki_dir / rel).exists() or any(r == rel for r, _ in planned):
                report.skipped += 1
                continue
            planned.append((rel, page))

        # Pages without index entries are orphans, which the gate rejects by design; update_index=False
        # therefore always takes the direct writer.
        api = None
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
        else:
            for rel, page in planned:
                target = self._wiki_dir / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(render_page(page), encoding="utf-8")
                report.written.append(rel)
                if update_index:
                    self._append_index(rel, page)
                    self._append_log(page, "created")
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
            extra={"memkernel_ref": memory.ref_id, "memory_type": memory.type.value},
        )

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
    """Index wiki pages as long-term memories: approved revisions only when wiki-studio is installed."""

    def __init__(self, service: MemoryService, wiki_dir: Path, project_root: Path | None = None) -> None:
        self._service = service
        self._wiki_dir = Path(wiki_dir)
        self._project_root = Path(project_root) if project_root is not None else self._wiki_dir.parent

    def import_pages(self, session_id: str | None = None) -> ImportReport:
        """Retain each importable page; return what was imported, skipped and why (memkernel-0-6 FR-010-FR-016)."""
        report = ImportReport()
        try:
            api = gate_available()
            reviews = review_pages(api, self._wiki_dir, self._project_root) if api is not None else None
        except GateError as exc:  # installed but broken, too old or failing: never fall back to the ungoverned path
            report.import_error = str(exc)
            logger.warning("wiki import from %s refused: %s", self._wiki_dir, exc)
            return report
        live = [m for m in self._service.list_memories(tier=MemoryTier.LONG_TERM) if WIKI_TAG in m.tags]
        if reviews is None:
            self._import_files(report, live, session_id)
        else:
            report.governed = True
            self._import_reviewed(reviews, report, live, session_id)
        return report

    def _import_files(self, report: ImportReport, live: list[Memory], session_id: str | None) -> None:
        """Without wiki-studio: every page file, drafts included (ungoverned, as before 0.6)."""
        for path in sorted(self._wiki_dir.rglob("*.md")):
            rel = path.relative_to(self._wiki_dir).as_posix()
            if rel.startswith(("schema/", "scripts/", ".")):
                continue
            page = parse_page(path.read_text(encoding="utf-8"))
            self._retain_page(rel, page, None, live, session_id, report)

    def _import_reviewed(
        self, reviews: list[PageReview], report: ImportReport, live: list[Memory], session_id: str | None
    ) -> None:
        for review in sorted(reviews, key=lambda r: r.path):
            if review.text is None:
                report.not_approved.append({"path": review.path, "state": review.state, "reason": review.reason})
                continue
            page = parse_page(review.text)
            ref_id = self._retain_page(review.path, page, review, live, session_id, report)
            if ref_id is not None and page is not None:
                self._reconcile(review.path, page, review, ref_id, report)

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
                continue  # corrected by an earlier revision of this page: still in effect
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
        """Retain one page; return its live memory's ref_id (new, or already current), or None when skipped."""
        memory_type = IMPORT_MAP.get(page.page_type) if page else None
        if page is None or memory_type is None or page.status == "deprecated":
            report.skipped.append(rel)
            return None
        content = f"{page.title}\n\n{page.body}".strip()
        tags = [WIKI_TAG, f"page:{page.slug}", f"page_type:{page.page_type}"]
        previous = self._previous(rel, review, live)
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
        supersedes = previous.ref_id if previous is not None and previous.content != content else None
        ref_id = self._service.retain(
            content=content,
            type=memory_type,
            session_id=session_id,
            source=rel,
            importance=0.9 if page.status == "stable" else 0.7,
            tags=tags,
            supersedes=supersedes,
        )
        report.imported.append(rel)
        return ref_id

    def _is_this_pages(self, ref_id: str, rel: str, review: PageReview) -> bool:
        """Whether ``ref_id`` is a memory imported from this page (any revision)."""
        memory = self._service.get(ref_id, touch=False)
        key_tag = f"{PAGE_KEY_TAG}{_tag_safe(review.page_key)}"
        return memory is not None and WIKI_TAG in memory.tags and (key_tag in memory.tags or memory.source == rel)

    @staticmethod
    def _previous(rel: str, review: PageReview | None, live: list[Memory]) -> Memory | None:
        """The page's live memory: by page key, else by its wiki-relative path (never by slug).

        The path fallback also covers a page whose key changed (a curator added a ``page_id``) and an edit read
        without wiki-studio after a governed import, so a page never ends up with two live memories.
        """
        if review is not None:
            key_tag = f"{PAGE_KEY_TAG}{_tag_safe(review.page_key)}"
            for memory in live:
                if key_tag in memory.tags:
                    return memory
        for memory in live:
            if memory.source == rel:
                return memory
        return None


def _tag_safe(value: str) -> str:
    """Tags are stored comma-separated: a comma in a page key would split it into two tags."""
    return value.replace("%", "%25").replace(",", "%2C")


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

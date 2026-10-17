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
    gate_available,
    lint_wiki,
    load_studio,
    propose_and_promote,
)

if TYPE_CHECKING:
    from memkernel.core.models import Memory
    from memkernel.core.services import MemoryService

logger = logging.getLogger(__name__)

WIKI_TAG = "wiki"
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
    gate_error: str | None = None  # the gate rejected the export; nothing was written


@dataclass
class ImportReport:
    """Outcome of an import run."""

    imported: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


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
        """Scaffold first (the gate cannot create index.md or log.md), then every page through propose + promote."""
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
        snapshot: _WikiSnapshot | None = None
        try:
            snapshot = _WikiSnapshot.take(self._wiki_dir)
            self._ensure_scaffold()
            propose_and_promote(api, pages, self._wiki_dir, self._project_root, self._proposals_dir, name)
        except (GateError, OSError) as exc:
            message = str(exc) if isinstance(exc, GateError) else f"the wiki could not be prepared for the gate: {exc}"
            if isinstance(exc, OSError):
                logger.warning("wiki export to %s failed: %s", self._wiki_dir, message)
            problems = snapshot.restore() if snapshot is not None else []
            if problems:
                message += "; the wiki could not be fully restored: " + "; ".join(problems)
                logger.warning("wiki export to %s left changes behind: %s", self._wiki_dir, "; ".join(problems))
            report.gate_error = message
            report.skipped += len(pages)
            return
        report.gated = True
        report.written.extend(page.path for page in pages)

    def _ensure_scaffold(self) -> None:
        self._wiki_dir.mkdir(parents=True, exist_ok=True)
        for name, text in ((INDEX_FILE, _index_scaffold()), (LOG_FILE, _log_scaffold())):
            path = self._wiki_dir / name
            if not path.exists():
                path.write_text(text, encoding="utf-8")

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


@dataclass
class _WikiSnapshot:
    """Every file a gated export can write, taken before it starts, so a failure restores exactly that.

    wiki-studio 0.3.1's promote rolls back only the writes that completed, and
    only on ``OSError``: a page or ``index.md`` whose write failed part-way stays
    as it was left. Its commit step writes every ``*.md`` of the staged wiki that
    differs from the live one, plus ``.audit/**/plan.json``, so the snapshot holds
    all of those as bytes (not only the files memkernel's edits change), and any
    such file that appears during the export is removed again.
    """

    wiki_dir: Path
    files: dict[Path, bytes]
    dirs: set[Path]  # directories that existed, the wiki directory included when it did

    @classmethod
    def take(cls, wiki_dir: Path) -> _WikiSnapshot:
        files = {path: path.read_bytes() for path in cls._tracked(wiki_dir)}
        dirs = {path for path in wiki_dir.rglob("*") if path.is_dir()} if wiki_dir.is_dir() else set()
        if wiki_dir.is_dir():
            dirs.add(wiki_dir)
        return cls(wiki_dir, files, dirs)

    @staticmethod
    def _tracked(wiki_dir: Path) -> list[Path]:
        if not wiki_dir.is_dir():
            return []
        return [
            path
            for path in wiki_dir.rglob("*")
            if path.is_file() and (path.suffix == ".md" or (path.name == "plan.json" and ".audit" in path.parts))
        ]

    def restore(self) -> list[str]:
        """Put every tracked file back; returns what could not be restored (empty = the wiki is as it was)."""
        problems: list[str] = []
        for path in self._tracked(self.wiki_dir):
            if path not in self.files:
                try:
                    path.unlink()
                except OSError as exc:
                    problems.append(self._problem(path, exc))
        for path, original in self.files.items():
            try:
                if not path.is_file() or path.read_bytes() != original:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(original)
            except OSError as exc:
                problems.append(self._problem(path, exc))
        created = [path for path in self.wiki_dir.rglob("*") if path.is_dir() and path not in self.dirs]
        if self.wiki_dir.is_dir() and self.wiki_dir not in self.dirs:
            created.append(self.wiki_dir)
        for directory in sorted(created, key=lambda d: len(d.parts), reverse=True):
            try:
                if not any(directory.iterdir()):
                    directory.rmdir()
            except OSError as exc:
                problems.append(self._problem(directory, exc))
        return problems

    def _problem(self, path: Path, exc: OSError) -> str:
        return f"{path.relative_to(self.wiki_dir.parent).as_posix()}: {exc}"


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
    """Index curated wiki pages as long-term memories."""

    def __init__(self, service: MemoryService, wiki_dir: Path) -> None:
        self._service = service
        self._wiki_dir = Path(wiki_dir)

    def import_pages(self, session_id: str | None = None) -> ImportReport:
        """Retain every page with a mapped page_type; return what was imported/skipped."""
        report = ImportReport()
        existing = {
            self._page_tag(m): m
            for m in self._service.list_memories(tier=MemoryTier.LONG_TERM)
            if WIKI_TAG in m.tags and self._page_tag(m)
        }
        for path in sorted(self._wiki_dir.rglob("*.md")):
            rel = path.relative_to(self._wiki_dir).as_posix()
            if rel.startswith(("schema/", "scripts/", ".")):
                continue
            page = parse_page(path.read_text(encoding="utf-8"))
            memory_type = IMPORT_MAP.get(page.page_type) if page else None
            if page is None or memory_type is None or page.status == "deprecated":
                report.skipped.append(rel)
                continue
            content = f"{page.title}\n\n{page.body}".strip()
            tags = [WIKI_TAG, f"page:{page.slug}", f"page_type:{page.page_type}"]
            previous = existing.get(f"page:{page.slug}")
            supersedes = previous.ref_id if previous is not None and previous.content != content else None
            self._service.retain(
                content=content,
                type=memory_type,
                session_id=session_id,
                source=rel,
                importance=0.9 if page.status == "stable" else 0.7,
                tags=tags,
                supersedes=supersedes,
            )
            report.imported.append(rel)
        return report

    @staticmethod
    def _page_tag(memory: Memory) -> str:
        for tag in memory.tags:
            if tag.startswith("page:"):
                return tag
        return ""

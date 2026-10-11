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

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from memkernel.core.models import MemoryTier, MemoryType
from memkernel.wiki.pages import WikiPage, parse_page, render_page, slugify

if TYPE_CHECKING:
    from memkernel.core.models import Memory
    from memkernel.core.services import MemoryService

logger = logging.getLogger(__name__)

WIKI_TAG = "wiki"
INDEX_FILE = "index.md"
LOG_FILE = "log.md"

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
    """Outcome of an export run."""

    written: list[str] = field(default_factory=list)
    skipped: int = 0


@dataclass
class ImportReport:
    """Outcome of an import run."""

    imported: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


class WikiExporter:
    """Compile long-term memories into draft wiki pages under ``wiki_dir``."""

    def __init__(self, service: MemoryService, wiki_dir: Path) -> None:
        self._service = service
        self._wiki_dir = Path(wiki_dir)

    def export(self, memories: list[Memory] | None = None, update_index: bool = True) -> ExportReport:
        """Write one page per exportable memory that is not already a wiki page.

        Memories that came from the wiki (tagged ``wiki``), chunk records, or
        memories a newer memory supersedes are skipped. Existing pages with
        the same slug are left untouched: the wiki, once written, is curated
        by humans/agents, not overwritten by the store.
        """
        report = ExportReport()
        candidates = memories if memories is not None else self._service.list_memories(tier=MemoryTier.LONG_TERM)
        superseded = {m.supersedes for m in candidates if m.supersedes}
        for memory in candidates:
            mapping = EXPORT_MAP.get(memory.type)
            if mapping is None or WIKI_TAG in memory.tags or memory.ref_id in superseded or memory.chunk_refs:
                report.skipped += 1
                continue
            page_type, directory = mapping
            page = self._page_for(memory, page_type)
            target = self._wiki_dir / directory / f"{page.slug}.md"
            if target.exists():
                report.skipped += 1
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(render_page(page), encoding="utf-8")
            rel = f"{directory}/{page.slug}.md"
            report.written.append(rel)
            if update_index:
                self._append_index(rel, page)
                self._append_log(page, "created")
        return report

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
        line = f"- [{page.title}]({rel}) — draft compiled from memkernel ({page.extra.get('memory_type', '')})."
        if not index.exists():
            index.write_text(
                "---\npage_type: index\nslug: index\ntitle: Wiki Index\nstatus: draft\n"
                f"last_reviewed: {_today()}\n---\n\n# Wiki Index\n\n## Compiled from memkernel\n\n",
                encoding="utf-8",
            )
        text = index.read_text(encoding="utf-8")
        if f"]({rel})" in text:
            return
        if not text.endswith("\n"):
            text += "\n"
        index.write_text(text + line + "\n", encoding="utf-8")

    def _append_log(self, page: WikiPage, verb: str) -> None:
        log = self._wiki_dir / LOG_FILE
        if not log.exists():
            log.write_text(
                "---\npage_type: log\nslug: log\ntitle: Wiki Edit Log\nstatus: draft\n"
                f"last_reviewed: {_today()}\n---\n\n# Wiki Edit Log\n\n## Entries\n\n",
                encoding="utf-8",
            )
        ref = page.extra.get("memkernel_ref", "")
        entry = f"- {_today()} — {verb} `{page.slug}` ({page.page_type}): compiled from memkernel {ref}\n"
        with log.open("a", encoding="utf-8") as fh:
            fh.write(entry)


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

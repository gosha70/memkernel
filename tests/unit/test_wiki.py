"""Unit tests for the LLM-wiki bridge: frontmatter parsing, export, import round-trip."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

import chromadb
import pytest

from memkernel.config import MemKernelSettings
from memkernel.core.models import MemoryTier, MemoryType
from memkernel.core.services import MemoryService
from memkernel.retrieval.search import HybridSearchService
from memkernel.retrieval.sparse import BM25Index
from memkernel.storage.chroma import ChromaVectorStore
from memkernel.wiki.pages import WikiPage, body_sections, parse_page, render_page, slugify
from memkernel.wiki.sync import WikiExporter, WikiImporter
from tests.conftest import MockEmbedding

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit

SAMPLE_PAGE = """---
page_type: decision
slug: use-postgres
title: "Use Postgres: not SQLite"
status: stable
last_reviewed: 2026-05-03
sources:
  - path: docs/adr/0003.md
    sha: 4c8cb5f
  - url: https://example.com/why
    retrieved: 2026-05-03
---

# Use Postgres

## Decision

Postgres for all services.

## Context

Concurrent writes.
"""


def _service(**overrides: Any) -> MemoryService:
    base: dict[str, Any] = {"project_id": f"wiki-{uuid.uuid4().hex[:8]}"}
    base.update(overrides)
    settings = MemKernelSettings(**base)
    store = ChromaVectorStore(settings, client=chromadb.EphemeralClient())
    sparse = BM25Index()
    search = HybridSearchService(store, MockEmbedding(), sparse, settings)
    return MemoryService(store, MockEmbedding(), sparse, search, settings)


# --------------------------------------------------------------------------
# pages
# --------------------------------------------------------------------------


def test_parse_page_reads_frontmatter_and_body() -> None:
    page = parse_page(SAMPLE_PAGE)
    assert page is not None
    assert page.page_type == "decision"
    assert page.slug == "use-postgres"
    assert page.title == "Use Postgres: not SQLite"
    assert page.status == "stable"
    assert page.sources == [
        {"path": "docs/adr/0003.md", "sha": "4c8cb5f"},
        {"url": "https://example.com/why", "retrieved": "2026-05-03"},
    ]
    assert body_sections(page.body) == {"Decision": "Postgres for all services.", "Context": "Concurrent writes."}


def test_parse_page_without_frontmatter_returns_none() -> None:
    assert parse_page("# just markdown\n") is None
    assert parse_page("---\ntitle: no type\n---\nbody\n") is None


def test_render_parse_round_trip() -> None:
    page = parse_page(SAMPLE_PAGE)
    assert page is not None
    again = parse_page(render_page(page))
    assert again == page


def test_render_quotes_values_with_colons() -> None:
    page = WikiPage(page_type="concept", slug="a", title="x: y", last_reviewed="2026-01-01")
    text = render_page(page)
    assert 'title: "x: y"' in text


def test_slugify() -> None:
    assert slugify("Use Postgres, not SQLite!") == "use-postgres-not-sqlite"
    assert slugify("   ") == "untitled"
    assert len(slugify("word " * 40)) <= 60


# --------------------------------------------------------------------------
# export
# --------------------------------------------------------------------------


def test_export_writes_draft_pages_index_and_log(tmp_path: Path) -> None:
    svc = _service()
    decision = svc.retain("Use Postgres for the user DB\n\nBecause of concurrent writes.", MemoryType.DECISION)
    svc.retain("Run `make verify` before every PR.", MemoryType.PROCEDURE)
    svc.retain("Ran the tests, all green.", MemoryType.EPISODE)
    svc.retain("def f(): pass", MemoryType.CODE)
    report = WikiExporter(svc, tmp_path).export()
    assert sorted(report.written) == [
        "decisions/use-postgres-for-the-user-db.md",
        "workflows/run-make-verify-before-every-pr.md",
    ]
    page = parse_page((tmp_path / "decisions/use-postgres-for-the-user-db.md").read_text())
    assert page is not None
    assert page.page_type == "decision" and page.status == "draft"
    assert page.extra["memkernel_ref"] == decision
    assert page.sources[0]["url"].startswith("memkernel://")
    sections = body_sections(page.body)
    assert list(sections) == ["Decision", "Context", "Alternatives considered", "Consequences"]
    assert "concurrent writes" in sections["Decision"]
    index = (tmp_path / "index.md").read_text()
    assert "(decisions/use-postgres-for-the-user-db.md)" in index
    log = (tmp_path / "log.md").read_text()
    assert "created `use-postgres-for-the-user-db` (decision)" in log


def test_export_is_idempotent_and_respects_existing_pages(tmp_path: Path) -> None:
    svc = _service()
    svc.retain("Use ruff for linting", MemoryType.CONVENTION)
    first = WikiExporter(svc, tmp_path).export()
    assert first.written == ["concepts/use-ruff-for-linting.md"]
    target = tmp_path / "concepts/use-ruff-for-linting.md"
    target.write_text(target.read_text().replace("status: draft", "status: stable"))
    second = WikiExporter(svc, tmp_path).export()
    assert second.written == []
    assert "status: stable" in target.read_text()
    assert (tmp_path / "index.md").read_text().count("use-ruff-for-linting.md") == 1


def test_export_skips_superseded_and_wiki_sourced(tmp_path: Path) -> None:
    svc = _service()
    old = svc.retain("Old rule", MemoryType.CONVENTION)
    svc.retain("New rule", MemoryType.CONVENTION, supersedes=old)
    svc.retain("From the wiki", MemoryType.FACT, tags=["wiki", "page:x"])
    report = WikiExporter(svc, tmp_path).export()
    assert report.written == ["concepts/new-rule.md"]
    # 0.4: list_memories already hides the superseded record (superseded_by), so only the wiki page is skipped here
    assert report.skipped == 1
    assert not (tmp_path / "concepts" / "old-rule.md").exists()


# --------------------------------------------------------------------------
# import
# --------------------------------------------------------------------------


def _write_wiki(root: Path) -> None:
    (root / "decisions").mkdir(parents=True)
    (root / "decisions/use-postgres.md").write_text(SAMPLE_PAGE)
    (root / "playbooks").mkdir()
    (root / "playbooks/restart-db.md").write_text(
        "---\npage_type: playbook\nslug: restart-db\ntitle: Restart DB\nstatus: draft\n"
        "last_reviewed: 2026-05-03\nsources:\n  - issue: 12\n---\n\n## Symptom\n\nDB hangs.\n"
    )
    (root / "schema").mkdir()
    (root / "schema/page-types.md").write_text("---\npage_type: concept\nslug: page-types\ntitle: x\n---\nskip me\n")
    (root / "index.md").write_text("---\npage_type: index\nslug: index\ntitle: Index\n---\n# Index\n")
    (root / "notes.md").write_text("no frontmatter here\n")


def test_import_indexes_pages_as_long_term_memories(tmp_path: Path) -> None:
    _write_wiki(tmp_path)
    svc = _service()
    report = WikiImporter(svc, tmp_path).import_pages()
    assert report.imported == ["decisions/use-postgres.md", "playbooks/restart-db.md"]
    assert set(report.skipped) == {"index.md", "notes.md"}
    memories = {m.source: m for m in svc.list_memories(tier=MemoryTier.LONG_TERM)}
    decision = memories["decisions/use-postgres.md"]
    assert decision.type == MemoryType.DECISION
    assert decision.importance == 0.9
    assert {"wiki", "page:use-postgres", "page_type:decision"} <= set(decision.tags)
    assert decision.content.startswith("Use Postgres: not SQLite")
    assert memories["playbooks/restart-db.md"].type == MemoryType.PROCEDURE
    assert memories["playbooks/restart-db.md"].importance == 0.7
    assert svc.recall("postgres concurrent writes", touch=False)[0].ref_id == decision.ref_id


def test_import_is_idempotent_and_supersedes_changed_pages(tmp_path: Path) -> None:
    _write_wiki(tmp_path)
    svc = _service()
    WikiImporter(svc, tmp_path).import_pages()
    WikiImporter(svc, tmp_path).import_pages()
    assert svc.count() == 2
    page = tmp_path / "decisions/use-postgres.md"
    page.write_text(page.read_text().replace("Concurrent writes.", "Concurrent writes and JSONB."))
    WikiImporter(svc, tmp_path).import_pages()
    assert svc.count() == 3
    results = svc.recall("postgres", type=MemoryType.DECISION, touch=False)
    assert len(results) == 1
    newest = svc.get(results[0].ref_id, touch=False)
    assert newest is not None and "JSONB" in newest.content and newest.supersedes is not None


def test_export_then_import_round_trip_does_not_duplicate(tmp_path: Path) -> None:
    svc = _service()
    svc.retain("Prefer composition over inheritance", MemoryType.CONVENTION)
    WikiExporter(svc, tmp_path).export()
    WikiImporter(svc, tmp_path).import_pages()
    # The wiki page is now a second, wiki-tagged memory; a second export must not re-emit it.
    assert WikiExporter(svc, tmp_path).export().written == []


def test_export_skips_document_memories(tmp_path: Path) -> None:
    """Documents are sources, not wiki pages: they never become draft pages."""
    svc = _service()
    svc.retain("# Spec\n\nA long document body.", MemoryType.DOCUMENT, source="specs/spec.md")
    svc.retain("Use Postgres", MemoryType.DECISION)
    report = WikiExporter(svc, tmp_path).export()
    assert report.written == ["decisions/use-postgres.md"]
    assert report.skipped == 1


def test_export_skips_superseded_by_marker_not_window(tmp_path: Path) -> None:
    """The exporter trusts the durable marker, not supersedes links among the fetched memories."""
    svc = _service()
    old = svc.retain("Use Celery for jobs", MemoryType.DECISION)
    svc.retain("Use arq for jobs", MemoryType.DECISION, supersedes=old)
    report = WikiExporter(svc, tmp_path).export()
    assert report.written == ["decisions/use-arq-for-jobs.md"]
    # export only the old memory: the marker still hides it even though its successor is not in the set
    old_memory = svc.get(old, touch=False)
    assert old_memory is not None and old_memory.superseded_by is not None
    report2 = WikiExporter(svc, tmp_path / "other").export(memories=[old_memory])
    assert report2.written == [] and report2.skipped == 1

# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""Records the wiki import manages are not revalidated against the project root (#160)."""

from __future__ import annotations

import importlib.util
import sys
import uuid
from pathlib import Path
from typing import Any

import chromadb
import pytest

from memkernel import recall_log
from memkernel.config import MemKernelSettings
from memkernel.core.models import NEEDS_REVIEW_KEY, REVIEW_REASON_KEY, WIKI_IDENTITY_TAGS, MemoryType
from memkernel.factory import build_service
from memkernel.lifecycle import MemoryLifecycle
from memkernel.wiki import sync
from memkernel.wiki.sync import WikiImporter
from tests.conftest import MockEmbedding

pytestmark = pytest.mark.unit

PAGE = (
    "---\npage_type: decision\nslug: use-postgres\ntitle: Use Postgres\nstatus: stable\n"
    "last_reviewed: 2026-05-03\nsources:\n  - path: docs/adr/0003.md\n---\n\n# Use Postgres\n\n"
    "## Decision\n\nPostgres for all services.\n"
)
REL = "decisions/use-postgres.md"
RUN = "run-160"
DIFF = Path(__file__).resolve().parents[2] / "eval" / "context-diff" / "diff.py"


def _diff_module() -> Any:
    spec = importlib.util.spec_from_file_location("context_diff_160", DIFF)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def _ungoverned(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without the wiki-studio gate the import reads the page files, as the ungoverned wiki tests do."""
    monkeypatch.setattr(sync, "gate_available", lambda: None)


def _layout(tmp_path: Path, layout: str) -> tuple[Path, Path]:
    """(project root, wiki folder) for the three layouts #160 reproduces."""
    project = tmp_path / "project"
    wiki = {"subfolder": project / "knowledge" / "wiki", "root": project, "outside": tmp_path / "wiki"}[layout]
    (wiki / "decisions").mkdir(parents=True, exist_ok=True)
    project.mkdir(parents=True, exist_ok=True)
    (wiki / REL).write_text(PAGE, encoding="utf-8")
    return project, wiki


def _setup(tmp_path: Path, layout: str) -> tuple[Any, MemKernelSettings, Path, WikiImporter]:
    project, wiki = _layout(tmp_path, layout)
    settings = MemKernelSettings(
        project_id=f"w-{uuid.uuid4().hex[:8]}",
        chroma_persist_path=str(tmp_path / "chroma"),
        state_dir=str(tmp_path / "state"),
        project_root=str(project),
        wiki_dir=str(wiki),
        wiki_mode="ungated",
        recall_log=True,
    )
    svc = build_service(settings, embedding=MockEmbedding(), chroma_client=chromadb.EphemeralClient())
    importer = WikiImporter(svc, wiki, project_root=project)
    assert importer.import_pages().imported == [REL]
    return svc, settings, project, importer


def _imported(svc: Any) -> Any:
    (decision,) = [m for m in svc.list_memories(type=MemoryType.DECISION) if m.source == REL]
    return decision


def _flag_missing(svc: Any, ref_id: str) -> None:
    """The flag revalidation saved on imported decisions before #160."""
    svc._vector_store.update_metadata(ref_id, {NEEDS_REVIEW_KEY: True, REVIEW_REASON_KEY: "missing"})


@pytest.mark.parametrize("layout", ["subfolder", "root", "outside"])
def test_an_imported_decision_is_never_flagged_in_any_layout(tmp_path: Path, layout: str) -> None:
    svc, settings, project, _ = _setup(tmp_path, layout)
    decision = _imported(svc)
    report = svc.consolidate(revalidate=True, purge=False)["revalidated"]
    assert report["flagged"] == [] and report["missing"] == 0 and report["checked"] == 0
    assert svc.get(decision.ref_id, touch=False).needs_review is False
    text = MemoryLifecycle(svc, settings).on_session_start("startup", session_id="s1")
    assert "### Needs review" not in text or decision.ref_id not in text.split("### Needs review", 1)[1]

    recall_log.append(
        settings,
        recall_log.ORIGIN_TOOL,
        [decision.ref_id],
        query="q",
        ids=recall_log.Correlation(RUN),
        memories=[decision],
    )
    diff = _diff_module()
    (judged,) = diff.diff(settings, RUN, store=svc._vector_store, root=project)["memories"]
    assert judged["statuses"] == ["unchanged"] and judged["notes"] == [diff.NOTE_WIKI]


def test_an_old_flag_on_an_imported_decision_is_cleared(tmp_path: Path) -> None:
    svc, _, _, _ = _setup(tmp_path, "subfolder")
    decision = _imported(svc)
    _flag_missing(svc, decision.ref_id)
    report = svc.consolidate(revalidate=True, purge=False)["revalidated"]
    assert report["cleared"] == 1 and report["flagged"] == []
    after = svc.get(decision.ref_id, touch=False)
    assert after.needs_review is False and after.review_reason == ""


def test_an_old_flag_clears_once_a_06_record_is_adopted(tmp_path: Path) -> None:
    """A 0.6 record (plain wiki tag, no identity tag) is still checked, so its flag stays; after
    wiki_import(adopt_legacy=true) gives it an identity tag, the next revalidation clears the flag."""
    svc, _, _, importer = _setup(tmp_path, "subfolder")
    decision = _imported(svc)
    identity = [t for t in decision.tags if t.startswith(WIKI_IDENTITY_TAGS)]
    svc._vector_store.merge_tags(decision.ref_id, remove=identity)  # what a 0.6 import wrote
    _flag_missing(svc, decision.ref_id)

    still = svc.consolidate(revalidate=True, purge=False)["revalidated"]
    assert [item["ref_id"] for item in still["flagged"]] == [decision.ref_id]

    importer.import_pages(adopt_legacy=True)
    adopted = svc.get(decision.ref_id, touch=False)
    assert any(t.startswith(WIKI_IDENTITY_TAGS) for t in adopted.tags)
    cleared = svc.consolidate(revalidate=True, purge=False)["revalidated"]
    assert cleared["cleared"] == 1 and cleared["flagged"] == []
    assert svc.get(decision.ref_id, touch=False).needs_review is False


def test_the_agents_own_decision_and_a_plain_wiki_tag_are_still_checked(tmp_path: Path) -> None:
    svc, _, project, _ = _setup(tmp_path, "subfolder")
    (project / "notes.md").write_text("Use Redis.\n", encoding="utf-8")
    own = svc.retain("Use Redis for sessions.", MemoryType.DECISION, source="notes.md")
    plain = svc.retain("Use Kafka.", MemoryType.DECISION, source="decisions/kafka.md", tags=["wiki"])
    (project / "notes.md").unlink()
    report = svc.consolidate(revalidate=True, purge=False)["revalidated"]
    assert {(item["ref_id"], item["reason"]) for item in report["flagged"]} == {(own, "missing"), (plain, "missing")}

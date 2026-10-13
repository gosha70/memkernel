"""Unit tests for code revalidation (0.4 US2): flags, boundary, recall exclusion, consolidate, lifecycle, endpoint."""

from __future__ import annotations

import os
import uuid
from typing import TYPE_CHECKING, Any

import chromadb
import pytest
from fastapi.testclient import TestClient

from memkernel.api.app import create_app
from memkernel.config import MemKernelSettings
from memkernel.core.models import MemoryType
from memkernel.core.services import MemoryService
from memkernel.factory import build_service
from memkernel.lifecycle import HEADING_NEEDS_REVIEW, MemoryLifecycle
from memkernel.retrieval.search import HybridSearchService
from memkernel.retrieval.sparse import BM25Index
from memkernel.storage.chroma import ChromaVectorStore
from tests.conftest import MockEmbedding

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit


class LineChunker:
    def chunk(self, content: str, metadata: dict[str, Any]) -> list[str]:
        return [part for part in content.split("\n\n") if part.strip()]


V1 = "def alpha():\n    return 'ALPHA-TOKEN-11'\n\ndef beta():\n    return 'BETA-TOKEN-22'\n"
V2 = "def alpha():\n    return 'ALPHA-TOKEN-11'\n\ndef beta():\n    return 'BETA-TOKEN-33'\n"


def _settings(root: Path, **overrides: Any) -> MemKernelSettings:
    base: dict[str, Any] = {
        "project_id": f"rv-{uuid.uuid4().hex[:8]}",
        "chroma_persist_path": "",
        "project_root": str(root),
    }
    base.update(overrides)
    return MemKernelSettings(**base)


def _build(root: Path) -> tuple[MemoryService, ChromaVectorStore, MemKernelSettings]:
    settings = _settings(root)
    store = ChromaVectorStore(settings, client=chromadb.EphemeralClient())
    embedding = MockEmbedding()
    sparse = BM25Index()
    search = HybridSearchService(store, embedding, sparse, settings)
    return MemoryService(store, embedding, sparse, search, settings, chunker=LineChunker()), store, settings


def _write(root: Path, rel: str, text: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


# --------------------------------------------------------------------------
# flags
# --------------------------------------------------------------------------


def test_unchanged_file_is_checked_and_not_flagged(tmp_path: Path) -> None:
    svc, _, _ = _build(tmp_path)
    _write(tmp_path, "src/app.py", V1)
    ref = svc.retain(V1, MemoryType.CODE, source="src/app.py")
    report = svc.revalidate()
    assert report == {"checked": 1, "changed": 0, "missing": 0, "cleared": 0, "unknown": 0, "flagged": []}
    memory = svc.get(ref, touch=False)
    assert memory is not None and memory.needs_review is False and memory.review_reason == ""


def test_changed_file_flags_canonical_and_owned_chunks(tmp_path: Path) -> None:
    svc, store, _ = _build(tmp_path)
    path = _write(tmp_path, "src/app.py", V1)
    ref = svc.retain(V1, MemoryType.CODE, source="src/app.py")
    path.write_text(V2, encoding="utf-8")
    report = svc.revalidate()
    assert (report["checked"], report["changed"]) == (1, 1)
    assert report["flagged"] == [{"ref_id": ref, "source": "src/app.py", "reason": "changed"}]
    memory = svc.get(ref, touch=False)
    assert memory is not None and memory.needs_review and memory.review_reason == "changed"
    chunks = store.list_all({"parent_ref": ref})
    assert chunks and all(c.needs_review and c.review_reason == "changed" for c in chunks)
    # a second pass is idempotent
    assert svc.revalidate()["changed"] == 1


def test_missing_file_flags_missing_and_restored_file_clears(tmp_path: Path) -> None:
    svc, store, _ = _build(tmp_path)
    path = _write(tmp_path, "src/app.py", V1)
    ref = svc.retain(V1, MemoryType.CODE, source="src/app.py")
    path.unlink()
    report = svc.revalidate()
    assert report["missing"] == 1 and report["flagged"][0]["reason"] == "missing"
    assert (svc.get(ref, touch=False) or None) is not None and svc.get(ref, touch=False).review_reason == "missing"  # type: ignore[union-attr]
    _write(tmp_path, "src/app.py", V1)
    report = svc.revalidate()
    assert report["cleared"] == 1 and report["flagged"] == []
    memory = svc.get(ref, touch=False)
    assert memory is not None and not memory.needs_review and memory.review_reason == ""
    assert all(not c.needs_review for c in store.list_all({"parent_ref": ref}))


def test_superseded_unsourced_and_chunk_records_are_skipped(tmp_path: Path) -> None:
    svc, _, _ = _build(tmp_path)
    path = _write(tmp_path, "src/app.py", V1)
    old = svc.retain(V1, MemoryType.CODE, source="src/app.py")
    svc.retain(V2, MemoryType.CODE, source="src/app.py")  # supersedes old
    svc.retain("print('no source')", MemoryType.CODE)
    path.write_text("changed again", encoding="utf-8")
    report = svc.revalidate()
    assert report["checked"] == 1  # only the live sourced canonical
    assert [f["ref_id"] for f in report["flagged"]] != [old]


# --------------------------------------------------------------------------
# boundary
# --------------------------------------------------------------------------


def test_sources_outside_the_project_root_are_unknown_and_never_read(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    outside = tmp_path / "outside.py"
    outside.write_text("secret", encoding="utf-8")
    svc, _, _ = _build(root)
    traversal = svc.retain(V1, MemoryType.CODE, source="../outside.py")
    absolute = svc.retain(V2, MemoryType.CODE, source=str(outside))
    link = root / "link.py"
    os.symlink(outside, link)
    symlinked = svc.retain(V1 + "\n", MemoryType.CODE, source="link.py")
    report = svc.revalidate()
    assert report["checked"] == 3 and report["unknown"] == 3 and report["flagged"] == []
    for ref in (traversal, absolute, symlinked):
        memory = svc.get(ref, touch=False)
        assert memory is not None and not memory.needs_review


def test_absolute_source_inside_the_root_is_allowed(tmp_path: Path) -> None:
    svc, _, _ = _build(tmp_path)
    path = _write(tmp_path, "src/app.py", V1)
    ref = svc.retain(V1, MemoryType.CODE, source=str(path))
    path.write_text(V2, encoding="utf-8")
    assert svc.revalidate()["flagged"] == [{"ref_id": ref, "source": str(path), "reason": "changed"}]


def test_unreadable_source_is_unknown(tmp_path: Path) -> None:
    svc, _, _ = _build(tmp_path)
    path = _write(tmp_path, "blob.bin", "x")
    svc.retain("x", MemoryType.CODE, source="blob.bin")
    path.write_bytes(b"\xff\xfe\x00invalid utf-8 \x80")
    report = svc.revalidate()
    assert report["unknown"] == 1 and report["flagged"] == []


# --------------------------------------------------------------------------
# recall exclusion
# --------------------------------------------------------------------------


def test_flagged_memory_leaves_default_recall_until_included(tmp_path: Path) -> None:
    svc, _, _ = _build(tmp_path)
    path = _write(tmp_path, "src/app.py", V1)
    ref = svc.retain(V1, MemoryType.CODE, source="src/app.py")
    assert ref in {r.ref_id for r in svc.recall("ALPHA-TOKEN-11", top_k=5)}
    path.write_text(V2, encoding="utf-8")
    svc.revalidate()
    hidden = {r.ref_id for r in svc.recall("ALPHA-TOKEN-11", top_k=5)}
    assert ref not in hidden and not any(r.startswith(f"{ref}-chunk-") for r in hidden)
    shown = {r.ref_id for r in svc.recall("ALPHA-TOKEN-11", top_k=5, include_needs_review=True)}
    assert ref in shown or any(r.startswith(f"{ref}-chunk-") for r in shown)
    # get and list_memories still return it
    assert svc.get(ref, touch=False) is not None
    assert ref in {m.ref_id for m in svc.list_memories(type=MemoryType.CODE)}


def test_record_without_the_needs_review_key_is_still_recalled(tmp_path: Path) -> None:
    svc, store, _ = _build(tmp_path)
    ref = svc.retain("Use arq", MemoryType.DECISION)
    raw = store._collection.get(ids=[ref], include=["metadatas"])["metadatas"][0]  # noqa: SLF001
    assert "needs_review" not in raw
    assert [r.ref_id for r in svc.recall("Use arq", top_k=1)] == [ref]


# --------------------------------------------------------------------------
# consolidate, lifecycle, endpoint
# --------------------------------------------------------------------------


def test_consolidate_revalidate_flag(tmp_path: Path) -> None:
    svc, _, _ = _build(tmp_path)
    path = _write(tmp_path, "src/app.py", V1)
    ref = svc.retain(V1, MemoryType.CODE, source="src/app.py")
    path.write_text(V2, encoding="utf-8")
    assert "revalidated" not in svc.consolidate()
    report = svc.consolidate(revalidate=True)
    assert report["revalidated"]["flagged"] == [{"ref_id": ref, "source": "src/app.py", "reason": "changed"}]
    assert report["purged"] == 0 and report["candidates"] == []


def test_session_start_lists_needs_review_only_when_flagged(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    svc = build_service(settings, embedding=MockEmbedding(), chroma_client=chromadb.EphemeralClient())
    lifecycle = MemoryLifecycle(svc, settings)
    path = _write(tmp_path, "src/app.py", V1)
    ref = svc.retain(V1, MemoryType.CODE, source="src/app.py")
    text = lifecycle.on_session_start()
    assert HEADING_NEEDS_REVIEW not in text
    path.write_text(V2, encoding="utf-8")
    text = lifecycle.on_session_start()
    assert f"{HEADING_NEEDS_REVIEW}\n- src/app.py — changed — {ref}\n" in text
    assert "retain the file again as code" in text
    # the 0.3 headings are untouched
    for heading in ("## Recovered from MemKernel (session start)", "### Latest checkpoint", "### Long-term context"):
        assert heading in text


def test_admin_revalidate_endpoint(tmp_path: Path) -> None:
    svc, _, _ = _build(tmp_path)
    path = _write(tmp_path, "src/app.py", V1)
    ref = svc.retain(V1, MemoryType.CODE, source="src/app.py")
    path.unlink()
    with TestClient(create_app(memory_service=svc)) as client:
        response = client.post("/revalidate")
    assert response.status_code == 200
    body = response.json()
    assert body["missing"] == 1 and body["flagged"][0]["ref_id"] == ref

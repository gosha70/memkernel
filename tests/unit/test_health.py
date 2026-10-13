"""Unit tests for the read-only store health pass (0.4 US3)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import chromadb
import pytest
from fastapi.testclient import TestClient

from memkernel.api.app import create_app
from memkernel.config import MemKernelSettings
from memkernel.core.models import HEALTH_CATEGORIES, HealthReport, MemoryType
from memkernel.core.services import MemoryService
from memkernel.factory import build_service
from memkernel.lifecycle import HEADING_STORE_HEALTH, MemoryLifecycle
from memkernel.retrieval.chunking import TokenChunker
from memkernel.retrieval.search import HybridSearchService
from memkernel.retrieval.sparse import BM25Index
from memkernel.storage.chroma import ChromaVectorStore
from memkernel.storage.documents import LocalDocumentStore
from tests.conftest import MockEmbedding

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit


class SlotEmbedding(MockEmbedding):
    """Deterministic: texts starting with the same word get identical one-hot vectors, others are orthogonal."""

    def __init__(self) -> None:
        super().__init__(dimension=8)
        self.calls = 0

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls += len(texts)
        out = []
        for text in texts:
            slot = (hash(text.split(" ", 1)[0]) if text else 0) % 8
            out.append([1.0 if i == slot else 0.0 for i in range(8)])
        return out


class LineChunker:
    def chunk(self, content: str, metadata: dict[str, Any]) -> list[str]:
        return [part for part in content.split("\n\n") if part.strip()]


class RecordingStore:
    """Proxy that records every list_all call's include_content flag."""

    def __init__(self, inner: ChromaVectorStore) -> None:
        self._inner = inner
        self.content_loads = 0

    def list_all(self, where: dict[str, Any] | None = None, include_content: bool = True) -> Any:
        if include_content:
            self.content_loads += 1
        return self._inner.list_all(where, include_content=include_content)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


def _settings(root: Path | None = None, **overrides: Any) -> MemKernelSettings:
    base: dict[str, Any] = {"project_id": f"hl-{uuid.uuid4().hex[:8]}", "chroma_persist_path": ""}
    if root is not None:
        base["project_root"] = str(root)
    base.update(overrides)
    return MemKernelSettings(**base)


def _build(
    settings: MemKernelSettings | None = None,
) -> tuple[MemoryService, ChromaVectorStore, SlotEmbedding, RecordingStore]:
    settings = settings or _settings()
    store = ChromaVectorStore(settings, client=chromadb.EphemeralClient())
    recorder = RecordingStore(store)
    embedding = SlotEmbedding()
    sparse = BM25Index()
    search = HybridSearchService(store, embedding, sparse, settings)
    svc = MemoryService(
        recorder,  # type: ignore[arg-type]
        embedding,
        sparse,
        search,
        settings,
        chunker=LineChunker(),
        document_store=LocalDocumentStore(store, embedding, sparse, settings),
        document_chunker=TokenChunker(settings),
    )
    return svc, store, embedding, recorder


def _backdate(store: ChromaVectorStore, ref_id: str, days: int) -> None:
    store.update_metadata(ref_id, {"timestamp": (datetime.now(UTC) - timedelta(days=days)).isoformat()})


def _raw(store: ChromaVectorStore, ref_id: str, content: str, **meta: Any) -> None:
    base = {
        "project_id": "hl",
        "session_id": "default",
        "timestamp": datetime.now(UTC).isoformat(),
        "type": "fact",
        "source": "",
        "hash": f"h-{ref_id}",
        "token_count": 1,
    }
    store.upsert(
        ref_id=ref_id, content=content, embedding=SlotEmbedding().embed([content])[0], metadata={**base, **meta}
    )


# --------------------------------------------------------------------------
# empty store, shape
# --------------------------------------------------------------------------


def test_empty_store_is_healthy() -> None:
    svc, _, _, _ = _build()
    report = svc.health()
    assert isinstance(report, HealthReport) and report.full
    assert report.summary == dict.fromkeys(HEALTH_CATEGORIES, 0)
    assert all(getattr(report, c) == [] for c in HEALTH_CATEGORIES)


# --------------------------------------------------------------------------
# one seeded defect per category
# --------------------------------------------------------------------------


def test_orphans_document_part_and_code_chunk() -> None:
    svc, store, _, _ = _build()
    doc = svc.retain("alpha " * 300, MemoryType.DOCUMENT, source="spec.md")
    code = svc.retain("def a():\n    pass\n\ndef b():\n    pass", MemoryType.CODE, source="src/x.py")
    store.delete(doc)
    store.delete(code)
    report = svc.health(full=False)
    orphans = {item.ref_id for item in report.orphans}
    assert any("document part" in i.detail for i in report.orphans)
    assert {f"{code}-chunk-0", f"{code}-chunk-1"} <= orphans
    assert report.counts["orphans"] == len(orphans) == report.summary["orphans"]
    # the dead parent_ref is a dangling link too
    assert {i.ref_id for i in report.dangling_links} >= {f"{code}-chunk-0", f"{code}-chunk-1"}


def test_dangling_links() -> None:
    svc, store, _, _ = _build()
    svc.retain("Use arq", MemoryType.DECISION, supersedes="never-existed")
    obs = svc.retain("seen once", MemoryType.OBSERVATION)
    promoted = svc.promote(obs, MemoryType.FACT, content="Durable fact")
    store.delete(obs)
    report = svc.health(full=False)
    details = {i.detail for i in report.dangling_links}
    assert "supersedes -> never-existed (missing)" in details
    assert f"promoted_from -> {obs} (missing)" in details
    assert promoted in {i.ref_id for i in report.dangling_links}


def test_unmarked_supersession_is_reported_not_fixed() -> None:
    svc, store, _, _ = _build()
    old = svc.retain("Old rule", MemoryType.CONVENTION)
    new = svc.retain("New rule", MemoryType.CONVENTION, supersedes=old)
    assert svc.health(full=False).unmarked_supersessions == []
    store.update_metadata(old, {"superseded_by": ""})  # a 0.2/0.3-style link without the marker
    report = svc.health(full=False)
    assert [i.ref_id for i in report.unmarked_supersessions] == [old]
    assert f"superseded by {new} without superseded_by" == report.unmarked_supersessions[0].detail
    assert (svc.get(old, touch=False) or None) is not None and svc.get(old, touch=False).superseded_by is None  # type: ignore[union-attr]


def test_stale_sources_code_only_inside_boundary(tmp_path: Path) -> None:
    svc, _, _, _ = _build(_settings(tmp_path))
    (tmp_path / "present.py").write_text("x = 1\n", encoding="utf-8")
    present = svc.retain("x = 1\n", MemoryType.CODE, source="present.py")
    gone = svc.retain("y = 2\n", MemoryType.CODE, source="gone.py")
    outside = svc.retain("z = 3\n", MemoryType.CODE, source="../outside.py")
    doc = svc.retain("a document body " * 50, MemoryType.DOCUMENT, source="not-a-path:label")
    report = svc.health(full=False)
    stale = {i.ref_id for i in report.stale_sources}
    assert stale == {gone}
    assert present not in stale and outside not in stale and doc not in stale


def test_needs_review_counts_each_file_once(tmp_path: Path) -> None:
    svc, _, _, _ = _build(_settings(tmp_path))
    path = tmp_path / "app.py"
    path.write_text("def a():\n    pass\n\ndef b():\n    pass\n", encoding="utf-8")
    ref = svc.retain(path.read_text(), MemoryType.CODE, source="app.py")
    path.write_text("changed", encoding="utf-8")
    svc.revalidate()
    report = svc.health(full=False)
    assert [i.ref_id for i in report.needs_review] == [ref]
    assert report.needs_review[0].detail == "app.py: changed"


def test_expired_present() -> None:
    svc, store, _, _ = _build(_settings(observation_ttl_days=7))
    stale = svc.retain("old observation", MemoryType.OBSERVATION)
    svc.retain("fresh observation", MemoryType.OBSERVATION)
    svc.retain("ancient decision", MemoryType.DECISION)
    _backdate(store, stale, days=30)
    report = svc.health(full=False)
    assert [i.ref_id for i in report.expired_present] == [stale]
    assert svc.get(stale, touch=False) is not None  # read-only: not purged


# --------------------------------------------------------------------------
# near-duplicates (full mode only)
# --------------------------------------------------------------------------


def test_near_duplicates_complete_within_candidate_set_and_exclusions() -> None:
    svc, store, _, _ = _build()
    a = svc.retain("alpha one", MemoryType.FACT)
    b = svc.retain("alpha two", MemoryType.DECISION)
    c = svc.retain("alpha three", MemoryType.CONVENTION)
    svc.retain("beta unrelated", MemoryType.FACT)
    report = svc.health()
    pairs = {frozenset(i.detail.split(" ")[1:2] + [i.ref_id]) for i in report.near_duplicates}
    assert pairs == {frozenset((a, b)), frozenset((a, c)), frozenset((b, c))}
    assert report.counts["near_duplicates"] == 3
    assert all("cosine 1.000" in i.detail for i in report.near_duplicates)
    # quick mode never computes them
    quick = svc.health(full=False)
    assert quick.near_duplicates == [] and quick.counts["near_duplicates"] == 0 and not quick.full


def test_near_duplicates_skip_linked_pairs_chunks_and_short_term() -> None:
    svc, store, _, _ = _build()
    old = svc.retain("alpha rule v1", MemoryType.FACT)
    new = svc.retain("alpha rule v2", MemoryType.DECISION, supersedes=old)  # old gets superseded_by: out of the set
    obs = svc.retain("alpha observed", MemoryType.OBSERVATION)
    promoted = svc.promote(obs, MemoryType.FACT, content="alpha promoted")
    assert promoted is not None
    code = svc.retain("alpha = 1\n\nalpha2 = 2", MemoryType.CODE, source="src/a.py")  # chunks start with alpha too
    report = svc.health()
    pairs = {frozenset((i.ref_id, i.detail.split(" ")[1])) for i in report.near_duplicates}
    # the three live, unlinked long-term records pair up; old (superseded), obs (short-term) and chunks never appear
    assert pairs == {frozenset((new, promoted)), frozenset((new, code)), frozenset((promoted, code))}
    assert report.counts["near_duplicates"] == 3


def test_pre_0_2_record_without_tier_label_is_found_as_neighbour() -> None:
    svc, store, _, _ = _build()
    new = svc.retain("alpha modern", MemoryType.FACT)
    _raw(store, "legacy-1", "alpha legacy")  # no tier key at all, type fact
    report = svc.health()
    assert {frozenset((i.ref_id, i.detail.split(" ")[1])) for i in report.near_duplicates} == {
        frozenset((new, "legacy-1"))
    }


def test_threshold_and_limit_are_settings() -> None:
    svc, _, _, _ = _build(_settings(health_duplicate_threshold=1.01))
    svc.retain("alpha one", MemoryType.FACT)
    svc.retain("alpha two", MemoryType.DECISION)
    assert svc.health().near_duplicates == []
    svc2, _, _, _ = _build(_settings(health_duplicate_limit=1))
    svc2.retain("alpha one", MemoryType.FACT)
    svc2.retain("alpha two", MemoryType.DECISION)
    assert svc2.health().near_duplicates == []


def test_report_items_are_bounded_but_counts_are_not() -> None:
    svc, store, _, _ = _build(_settings(health_report_limit=2))
    for i in range(5):
        svc.retain(f"decision {i}", MemoryType.DECISION, supersedes=f"missing-{i}")
    report = svc.health(full=False)
    assert report.counts["dangling_links"] == 5 and len(report.dangling_links) == 2


# --------------------------------------------------------------------------
# cost contract, surfaces
# --------------------------------------------------------------------------


def test_quick_health_on_500_records_loads_no_content_and_embeds_nothing() -> None:
    svc, store, embedding, recorder = _build()
    for i in range(500):
        _raw(store, f"r{i}", f"record {i}", type="decision" if i % 2 else "episode")
    embedding.calls = 0
    recorder.content_loads = 0
    report = svc.health(full=False)
    assert report.summary["orphans"] == 0
    assert embedding.calls == 0
    assert recorder.content_loads == 0
    svc.health()
    assert recorder.content_loads == 1 and embedding.calls >= 250


def test_admin_health_store_endpoint_and_plain_health_unchanged() -> None:
    svc, _, _, _ = _build()
    svc.retain("Use arq", MemoryType.DECISION, supersedes="never-existed")
    with TestClient(create_app(memory_service=svc)) as client:
        plain = client.get("/health").json()
        store_report = client.get("/health/store").json()
    assert set(plain) == {"status", "project_id", "collection_count", "memory_count"}
    assert store_report["summary"]["dangling_links"] == 1
    assert store_report["dangling_links"][0]["detail"] == "supersedes -> never-existed (missing)"
    assert store_report["full"] is True


def test_consolidate_carries_the_quick_summary() -> None:
    svc, _, _, _ = _build()
    svc.retain("Use arq", MemoryType.DECISION, supersedes="never-existed")
    report = svc.consolidate()
    assert report["health"]["dangling_links"] == 1 and "near_duplicates" in report["health"]


def test_session_start_prints_store_health_only_when_something_is_wrong() -> None:
    settings = _settings()
    svc = build_service(settings, embedding=MockEmbedding(), chroma_client=chromadb.EphemeralClient())
    lifecycle = MemoryLifecycle(svc, settings)
    assert HEADING_STORE_HEALTH not in lifecycle.on_session_start()
    svc.retain("Use arq", MemoryType.DECISION, supersedes="never-existed")
    text = lifecycle.on_session_start()
    expected = "orphans 0, dangling links 1, unmarked supersessions 0, stale sources 0, needs review 0, expired 0"
    assert f"{HEADING_STORE_HEALTH}\n{expected}" in text


def _pair_set(report: HealthReport) -> set[frozenset[str]]:
    return {frozenset((i.ref_id, i.detail.split(" ")[1])) for i in report.near_duplicates}


def test_near_duplicate_pair_is_reported_once_with_smaller_id_first() -> None:
    svc, _, _, _ = _build()
    a = svc.retain("alpha one", MemoryType.FACT)
    b = svc.retain("alpha two", MemoryType.DECISION)
    report = svc.health()
    assert len(report.near_duplicates) == 1
    item = report.near_duplicates[0]
    assert item.ref_id == min(a, b)
    assert item.detail.startswith(f"~ {max(a, b)} (cosine ")
    assert _pair_set(report) == {frozenset((a, b))}


def test_pair_survives_when_only_one_query_direction_clears_the_threshold() -> None:
    """An approximate index may score A->B below the threshold and B->A above it: the pair is kept."""
    svc, store, _, _ = _build()
    a = svc.retain("alpha one", MemoryType.FACT)
    b = svc.retain("alpha two", MemoryType.DECISION)
    original = store.search_dense
    state = {"queries": 0}

    def asymmetric(query_embedding: list[float], top_k: int, where: dict[str, Any] | None = None) -> Any:
        results = original(query_embedding, top_k, where)
        state["queries"] += 1
        if state["queries"] == 1:  # first direction only: every neighbour scores below the threshold
            return [r.model_copy(update={"score": 0.5}) for r in results]
        return results

    store.search_dense = asymmetric  # type: ignore[method-assign]
    report = svc.health()
    assert state["queries"] == 2
    assert _pair_set(report) == {frozenset((a, b))}
    assert "cosine 1.000" in report.near_duplicates[0].detail

"""Unit tests for sourced-code identity, owner-specific chunk records and durable supersession (0.4 US1)."""

from __future__ import annotations

import uuid
from typing import Any

import chromadb
import pytest

from memkernel.config import MemKernelSettings
from memkernel.core.models import CODE_CHUNK_TAG, MemoryTier, MemoryType
from memkernel.core.services import MemoryService
from memkernel.retrieval.search import HybridSearchService
from memkernel.retrieval.sparse import BM25Index
from memkernel.storage.chroma import ChromaVectorStore
from memkernel.wiki.sync import WikiExporter
from tests.conftest import MockEmbedding

pytestmark = pytest.mark.unit


class CountingEmbedding(MockEmbedding):
    def __init__(self) -> None:
        super().__init__()
        self.texts = 0

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.texts += len(texts)
        return super().embed(texts)


class LineChunker:
    """Chunks on blank lines so tests control chunk boundaries exactly."""

    def chunk(self, content: str, metadata: dict[str, Any]) -> list[str]:
        return [part for part in content.split("\n\n") if part.strip()]


def _settings(**overrides: Any) -> MemKernelSettings:
    base: dict[str, Any] = {"project_id": f"code-{uuid.uuid4().hex[:8]}", "chroma_persist_path": ""}
    base.update(overrides)
    return MemKernelSettings(**base)


def _build(
    chunker: Any = None, embedding: MockEmbedding | None = None
) -> tuple[MemoryService, ChromaVectorStore, MockEmbedding]:
    settings = _settings()
    store = ChromaVectorStore(settings, client=chromadb.EphemeralClient())
    embedding = embedding or MockEmbedding()
    sparse = BM25Index()
    search = HybridSearchService(store, embedding, sparse, settings)
    svc = MemoryService(store, embedding, sparse, search, settings, chunker=chunker or LineChunker())
    return svc, store, embedding


V1 = "def shared():\n    return 1\n\ndef only_in_v1():\n    return 'OLDMARKER-7731'"
V2 = "def shared():\n    return 1\n\ndef only_in_v2():\n    return 'NEWMARKER-9902'"


def _chunks_of(store: ChromaVectorStore, ref_id: str) -> list[Any]:
    return store.list_all({"parent_ref": ref_id})


# --------------------------------------------------------------------------
# identity
# --------------------------------------------------------------------------


def test_same_content_same_source_dedups_and_embeds_nothing() -> None:
    svc, store, embedding = _build(embedding=CountingEmbedding())
    assert isinstance(embedding, CountingEmbedding)
    ref1 = svc.retain(V1, MemoryType.CODE, source="src/a.py")
    after = embedding.texts
    assert after == 3  # canonical + 2 chunks
    ref2 = svc.retain(V1, MemoryType.CODE, source="src/a.py", session_id="s2", tags=["again"])
    assert ref2 == ref1
    assert embedding.texts == after
    memory = svc.get(ref1, touch=False)
    assert memory is not None and memory.session_id == "s2" and memory.tags == ["again"]
    assert store.count() == 3


def test_same_content_under_another_path_is_its_own_record() -> None:
    svc, store, _ = _build()
    a = svc.retain(V1, MemoryType.CODE, source="src/a.py")
    b = svc.retain(V1, MemoryType.CODE, source="src/b.py")
    assert a != b
    assert {m.source for m in (svc.get(a, touch=False), svc.get(b, touch=False)) if m} == {"src/a.py", "src/b.py"}
    for ref in (a, b):
        memory = svc.get(ref, touch=False)
        assert memory is not None and memory.superseded_by is None
    assert store.count() == 6
    # a change to one path never touches the other
    a2 = svc.retain(V2, MemoryType.CODE, source="src/a.py")
    assert a2 != a
    assert (svc.get(b, touch=False) or None) is not None and svc.get(b, touch=False).superseded_by is None  # type: ignore[union-attr]


def test_unsourced_code_keeps_global_dedup() -> None:
    svc, _, _ = _build()
    ref1 = svc.retain("print('x')", MemoryType.CODE)
    ref2 = svc.retain("print('x')", MemoryType.CODE)
    assert ref1 == ref2
    memory = svc.get(ref1, touch=False)
    assert memory is not None and memory.superseded_by is None


def test_single_chunk_file_cannot_shadow_its_canonical() -> None:
    svc, store, _ = _build()
    body = "def only():\n    return 42"  # one chunk equal to the whole file
    ref = svc.retain(body, MemoryType.CODE, source="src/one.py")
    chunks = _chunks_of(store, ref)
    assert len(chunks) == 1 and chunks[0].content == body
    found = store.find_by_hash(chunks[0].content_hash, "code", source="src/one.py")
    assert found is not None and found.ref_id == ref  # the canonical, not the chunk
    assert svc.retain(body, MemoryType.CODE, source="src/one.py") == ref


# --------------------------------------------------------------------------
# owner-specific chunks
# --------------------------------------------------------------------------


def test_chunks_are_owner_specific_and_tagged() -> None:
    svc, store, _ = _build()
    a = svc.retain(V1, MemoryType.CODE, source="src/a.py")
    b = svc.retain(V1, MemoryType.CODE, source="src/b.py")
    chunks_a, chunks_b = _chunks_of(store, a), _chunks_of(store, b)
    assert [c.ref_id for c in chunks_a] == [f"{a}-chunk-0", f"{a}-chunk-1"]
    assert [c.ref_id for c in chunks_b] == [f"{b}-chunk-0", f"{b}-chunk-1"]
    assert all(CODE_CHUNK_TAG in c.tags and c.parent_ref == a and c.source == "src/a.py" for c in chunks_a)
    canonical = svc.get(a, touch=False)
    assert canonical is not None and canonical.chunk_refs == [f"{a}-chunk-0", f"{a}-chunk-1"]
    # the shared function exists once per owner (chunk records only; canonicals start with it too)
    shared = [m for m in store.list_all() if m.parent_ref is not None and m.content.startswith("def shared")]
    assert len(shared) == 2


def test_supersession_keeps_shared_chunk_under_the_new_owner_only() -> None:
    svc, store, _ = _build()
    old = svc.retain(V1, MemoryType.CODE, source="src/a.py")
    new = svc.retain(V2, MemoryType.CODE, source="src/a.py")
    assert new != old
    assert _chunks_of(store, old) == []
    new_chunks = _chunks_of(store, new)
    assert len(new_chunks) == 2
    assert any(c.content.startswith("def shared") for c in new_chunks)
    old_memory, new_memory = svc.get(old, touch=False), svc.get(new, touch=False)
    assert old_memory is not None and old_memory.superseded_by == new
    assert old_memory.content == V1  # provenance survives
    assert new_memory is not None and new_memory.supersedes == old and new_memory.superseded_by is None


def test_old_only_phrase_is_hidden_after_supersession() -> None:
    svc, _, _ = _build()
    old = svc.retain(V1, MemoryType.CODE, source="src/a.py")
    new = svc.retain(V2, MemoryType.CODE, source="src/a.py")
    old_hits = {r.ref_id for r in svc.recall("OLDMARKER-7731", top_k=5)}
    assert old not in old_hits and not any(r.startswith(f"{old}-chunk-") for r in old_hits)
    new_hits = [r.ref_id for r in svc.recall("NEWMARKER-9902", top_k=5)]
    assert new_hits and all(r == new or r.startswith(f"{new}-chunk-") for r in new_hits)


def test_several_live_canonicals_are_all_superseded() -> None:
    """A pre-0.4 store can hold two unsuperseded snapshots of one path; one retain replaces both."""
    svc, store, _ = _build()
    first = svc.retain(V1, MemoryType.CODE, source="src/a.py")
    store.update_metadata(first, {"superseded_by": ""})  # (defensive: marker absent)
    # simulate a second legacy live snapshot of the same path without the supersession link
    second = svc.retain(V2, MemoryType.CODE, source="src/a.py")
    store.update_metadata(first, {"superseded_by": ""})
    store.update_metadata(second, {"supersedes": ""})
    assert len(svc._live_code_canonicals("src/a.py")) == 2  # noqa: SLF001
    third = svc.retain(V1 + "\n\ndef v3():\n    pass", MemoryType.CODE, source="src/a.py")
    for ref in (first, second):
        memory = svc.get(ref, touch=False)
        assert memory is not None and memory.superseded_by == third
    assert [m.ref_id for m in svc._live_code_canonicals("src/a.py")] == [third]  # noqa: SLF001


def test_explicit_supersedes_sets_the_marker_on_any_type() -> None:
    svc, _, _ = _build()
    old = svc.retain("Use Celery", MemoryType.DECISION)
    new = svc.retain("Use arq", MemoryType.DECISION, supersedes=old)
    old_memory = svc.get(old, touch=False)
    assert old_memory is not None and old_memory.superseded_by == new
    # dedup hit carrying supersedes marks the target too
    other = svc.retain("Use Celery again", MemoryType.DECISION)
    svc.retain("Use arq", MemoryType.DECISION, supersedes=other)
    assert (svc.get(other, touch=False) or None) is not None and svc.get(other, touch=False).superseded_by == new  # type: ignore[union-attr]


def test_list_consolidate_and_wiki_export_honour_the_marker(tmp_path: Any) -> None:
    svc, store, _ = _build()
    old = svc.retain("Use Celery", MemoryType.DECISION)
    new = svc.retain("Use arq", MemoryType.DECISION, supersedes=old)
    obs_old = svc.retain("flaky test", MemoryType.OBSERVATION)
    svc.retain("flaky test fixed", MemoryType.OBSERVATION, supersedes=obs_old)
    listed = {m.ref_id for m in svc.list_memories()}
    assert new in listed and old not in listed
    assert old in {m.ref_id for m in svc.list_memories(include_superseded=True)}
    assert obs_old not in {c["ref_id"] for c in svc.consolidate()["candidates"]}
    report = WikiExporter(svc, tmp_path).export()
    assert report.written == ["decisions/use-arq.md"]
    # a marker set without any supersedes link on the fetched set still hides the record
    lone = svc.retain("Lone decision", MemoryType.DECISION)
    store.update_metadata(lone, {"superseded_by": "gone-elsewhere"})
    assert lone not in {m.ref_id for m in svc.list_memories()}
    assert lone not in {r.ref_id for r in svc.recall("Lone decision", top_k=5)}


def test_chunk_whose_owner_is_gone_is_dropped_from_recall() -> None:
    svc, store, _ = _build()
    ref = svc.retain(V1, MemoryType.CODE, source="src/a.py")
    store.delete(ref)  # owner vanishes without forget(): orphan chunks remain
    assert _chunks_of(store, ref)
    assert not any(r.ref_id.startswith(f"{ref}-chunk-") for r in svc.recall("OLDMARKER-7731", top_k=5))


# --------------------------------------------------------------------------
# forget and legacy chunk_refs
# --------------------------------------------------------------------------


def test_forget_deletes_owned_chunks() -> None:
    svc, store, _ = _build()
    ref = svc.retain(V1, MemoryType.CODE, source="src/a.py")
    keep = svc.retain(V1, MemoryType.CODE, source="src/b.py")
    assert svc.forget(ref) is True
    assert _chunks_of(store, ref) == []
    assert len(_chunks_of(store, keep)) == 2
    assert store.count() == 3


def test_legacy_shared_chunk_is_deleted_only_when_unreferenced() -> None:
    svc, store, _ = _build()
    # two legacy canonicals sharing one untagged chunk record through chunk_refs
    shared = svc.retain("def shared(): pass", MemoryType.CODE)  # plain code record standing in for a legacy chunk
    a = svc.retain("# file a\ndef shared(): pass", MemoryType.CODE, source="legacy/a.py")
    b = svc.retain("# file b\ndef shared(): pass", MemoryType.CODE, source="legacy/b.py")
    for ref in (a, b):
        store.update_metadata(ref, {"chunk_refs": shared})
    assert svc.forget(a) is True
    assert store.get_by_id(shared) is not None  # b still references it
    assert svc.forget(b) is True
    assert store.get_by_id(shared) is None


def _legacy_chunk(store: ChromaVectorStore, ref_id: str, content: str, source: str) -> str:
    """Write a pre-0.4 chunk record: plain `code` record, same source, no tag, no parent_ref."""
    memory = store.list_all()[0]
    store.upsert(
        ref_id=ref_id,
        content=content,
        embedding=MockEmbedding().embed([content])[0],
        metadata={
            "project_id": memory.project_id,
            "session_id": "default",
            "timestamp": memory.timestamp.isoformat(),
            "type": "code",
            "source": source,
            "hash": f"legacy-{ref_id}",
            "token_count": 1,
        },
    )
    return ref_id


def test_legacy_chunk_is_recognised_through_chunk_refs() -> None:
    svc, store, _ = _build()
    canonical = svc.retain("# file\ndef f(): pass", MemoryType.CODE, source="legacy/f.py")
    legacy_chunk = _legacy_chunk(store, "legacy-chunk-1", "def f(): pass", "legacy/f.py")
    store.update_metadata(canonical, {"chunk_refs": legacy_chunk})
    assert [m.ref_id for m in svc._live_code_canonicals("legacy/f.py")] == [canonical]  # noqa: SLF001
    new = svc.retain("# file v2\ndef f(): return 1", MemoryType.CODE, source="legacy/f.py")
    assert (svc.get(canonical, touch=False) or None) is not None and svc.get(
        canonical, touch=False
    ).superseded_by == new  # type: ignore[union-attr]
    assert store.get_by_id(legacy_chunk) is None  # unreferenced legacy chunk cleaned up


def test_retain_code_without_chunker_has_no_chunks() -> None:
    settings = _settings()
    store = ChromaVectorStore(settings, client=chromadb.EphemeralClient())
    sparse = BM25Index()
    svc = MemoryService(
        store, MockEmbedding(), sparse, HybridSearchService(store, MockEmbedding(), sparse, settings), settings
    )
    ref = svc.retain(V1, MemoryType.CODE, source="src/a.py")
    assert store.count() == 1
    memory = svc.get(ref, touch=False)
    assert memory is not None and memory.chunk_refs == [] and memory.tier == MemoryTier.LONG_TERM


# --------------------------------------------------------------------------
# PR #12 round 2: reverted content, dedup refresh, split-brain, superseded owners
# --------------------------------------------------------------------------


def test_reverting_a_file_creates_a_new_live_record_not_the_superseded_one() -> None:
    svc, store, _ = _build()
    v1 = svc.retain(V1, MemoryType.CODE, source="src/a.py")
    v2 = svc.retain(V2, MemoryType.CODE, source="src/a.py")
    back = svc.retain(V1, MemoryType.CODE, source="src/a.py")
    assert back not in (v1, v2)
    live = [m.ref_id for m in svc._live_code_canonicals("src/a.py")]  # noqa: SLF001
    assert live == [back]
    # provenance chain: v1 was replaced by v2, v2 by the reverted record
    v1_memory, v2_memory = svc.get(v1, touch=False), svc.get(v2, touch=False)
    assert v1_memory is not None and v1_memory.superseded_by == v2
    assert v2_memory is not None and v2_memory.superseded_by == back
    assert (svc.get(back, touch=False) or None) is not None and svc.get(back, touch=False).supersedes == v2  # type: ignore[union-attr]
    assert len(_chunks_of(store, back)) == 2 and _chunks_of(store, v1) == [] and _chunks_of(store, v2) == []
    hits = {r.ref_id for r in svc.recall("OLDMARKER-7731", top_k=5)}
    assert hits and all(h == back or h.startswith(f"{back}-chunk-") for h in hits)


def test_superseded_record_of_any_type_is_not_a_dedup_hit() -> None:
    svc, _, _ = _build()
    old = svc.retain("Use Celery", MemoryType.DECISION)
    new = svc.retain("Use arq", MemoryType.DECISION, supersedes=old)
    again = svc.retain("Use Celery", MemoryType.DECISION)
    assert again != old
    memory = svc.get(again, touch=False)
    assert memory is not None and memory.superseded_by is None
    assert (svc.get(old, touch=False) or None) is not None and svc.get(old, touch=False).superseded_by == new  # type: ignore[union-attr]


def test_dedup_refresh_moves_owned_chunks_to_the_new_session() -> None:
    svc, store, _ = _build()
    ref = svc.retain(V1, MemoryType.CODE, source="src/a.py", session_id="s1")
    assert {c.session_id for c in _chunks_of(store, ref)} == {"s1"}
    assert svc.retain(V1, MemoryType.CODE, source="src/a.py", session_id="s2", checkpoint=True) == ref
    chunks = _chunks_of(store, ref)
    assert {c.session_id for c in chunks} == {"s2"} and all(c.checkpoint for c in chunks)
    s1_hits = {r.ref_id for r in svc.recall("OLDMARKER-7731", session_id="s1", top_k=5)}
    assert ref not in s1_hits and not any(r.startswith(f"{ref}-chunk-") for r in s1_hits)
    s2_hits = {r.ref_id for r in svc.recall("OLDMARKER-7731", session_id="s2", top_k=5)}
    assert s2_hits and all(r == ref or r.startswith(f"{ref}-chunk-") for r in s2_hits)


def test_chunk_hit_must_satisfy_the_query_through_its_owner() -> None:
    svc, store, _ = _build()
    ref = svc.retain(V1, MemoryType.CODE, source="src/a.py", session_id="s1")
    # even if a chunk's own metadata drifted, the owner decides
    for chunk in _chunks_of(store, ref):
        store.update_metadata(chunk.ref_id, {"session_id": "other"})
    hits = {r.ref_id for r in svc.recall("OLDMARKER-7731", session_id="other", top_k=5)}
    assert not any(r.startswith(f"{ref}-chunk-") for r in hits)


class FlakyEmbedding(MockEmbedding):
    """Fails on batches (the chunk index) while ``fail`` is set; single texts (the canonical) always succeed."""

    def __init__(self) -> None:
        super().__init__()
        self.fail = False

    def embed(self, texts: list[str]) -> list[list[float]]:
        if self.fail and len(texts) > 1:
            raise RuntimeError("embedding backend down")
        return super().embed(texts)


def test_failed_chunk_index_is_compensated_and_a_retry_converges() -> None:
    embedding = FlakyEmbedding()
    svc, store, _ = _build(embedding=embedding)
    v1 = svc.retain(V1, MemoryType.CODE, source="src/a.py")
    before = store.count()
    embedding.fail = True
    with pytest.raises(RuntimeError, match="backend down"):
        svc.retain(V2, MemoryType.CODE, source="src/a.py")
    # nothing half-written: v1 is still the only live snapshot, with its chunks
    assert store.count() == before
    assert [m.ref_id for m in svc._live_code_canonicals("src/a.py")] == [v1]  # noqa: SLF001
    assert len(_chunks_of(store, v1)) == 2
    embedding.fail = False
    v2 = svc.retain(V2, MemoryType.CODE, source="src/a.py")
    assert v2 != v1
    assert [m.ref_id for m in svc._live_code_canonicals("src/a.py")] == [v2]  # noqa: SLF001
    assert (svc.get(v1, touch=False) or None) is not None and svc.get(v1, touch=False).superseded_by == v2  # type: ignore[union-attr]
    assert len(_chunks_of(store, v2)) == 2 and _chunks_of(store, v1) == []


def test_dedup_hit_finishes_an_interrupted_retain() -> None:
    """A canonical written without chunks or supersession (crash mid-retain) is completed by the next retain."""
    svc, store, _ = _build()
    v1 = svc.retain(V1, MemoryType.CODE, source="src/a.py")
    sample = store.list_all()[0]
    half = "half-written-v2"
    store.upsert(
        ref_id=half,
        content=V2,
        embedding=MockEmbedding().embed([V2])[0],
        metadata={
            "project_id": sample.project_id,
            "session_id": "default",
            "timestamp": sample.timestamp.isoformat(),
            "type": "code",
            "source": "src/a.py",
            "hash": __import__("memkernel.memory.dedup", fromlist=["compute_content_hash"]).compute_content_hash(V2),
            "token_count": 1,
        },
    )
    assert {m.ref_id for m in svc._live_code_canonicals("src/a.py")} == {v1, half}  # noqa: SLF001
    assert svc.retain(V2, MemoryType.CODE, source="src/a.py") == half
    assert [m.ref_id for m in svc._live_code_canonicals("src/a.py")] == [half]  # noqa: SLF001
    assert len(_chunks_of(store, half)) == 2 and _chunks_of(store, v1) == []
    half_memory, v1_memory = svc.get(half, touch=False), svc.get(v1, touch=False)
    assert half_memory is not None and half_memory.supersedes == v1 and half_memory.chunk_refs
    assert v1_memory is not None and v1_memory.superseded_by == half

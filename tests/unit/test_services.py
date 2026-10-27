"""Unit tests for MemoryService."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock

import chromadb
import pytest

from memkernel.config import MemKernelSettings
from memkernel.core.models import MemoryType
from memkernel.core.services import MemoryService
from memkernel.retrieval.search import HybridSearchService
from memkernel.retrieval.sparse import BM25Index
from memkernel.storage.chroma import ChromaVectorStore
from tests.conftest import MockEmbedding

# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _make_settings(**overrides: Any) -> MemKernelSettings:
    # Use a unique project_id per call so each test gets its own ChromaDB
    # collection; EphemeralClient shares in-process state by collection name.
    base: dict[str, Any] = {
        "project_id": f"test-{uuid.uuid4().hex[:8]}",
        "default_session_id": "default",
        "rrf_k": 60,
        "search_top_k": 5,
        "preview_length": 200,
        "episode_ttl_days": 30,
    }
    base.update(overrides)
    return MemKernelSettings(**base)


def _make_service(
    settings: MemKernelSettings | None = None,
    sparse: BM25Index | None = None,
    chunker: Any = None,
) -> tuple[MemoryService, ChromaVectorStore, BM25Index]:
    if settings is None:
        settings = _make_settings()
    if sparse is None:
        sparse = BM25Index()
    store = ChromaVectorStore(settings, client=chromadb.EphemeralClient())
    embedding = MockEmbedding()
    search_svc = HybridSearchService(store, embedding, sparse, settings)
    svc = MemoryService(store, embedding, sparse, search_svc, settings, chunker=chunker)
    return svc, store, sparse


# ---------------------------------------------------------------------------
# retain — basic
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_retain_new_content_returns_ref_id() -> None:
    svc, store, _ = _make_service()
    ref_id = svc.retain("Use ruff for linting.", MemoryType.CONVENTION)
    assert isinstance(ref_id, str)
    assert len(ref_id) > 0


@pytest.mark.unit
def test_retain_new_content_get_returns_memory() -> None:
    svc, store, _ = _make_service()
    ref_id = svc.retain("Use ruff for linting.", MemoryType.CONVENTION, session_id="sess-1")
    memory = svc.get(ref_id)
    assert memory is not None
    assert memory.ref_id == ref_id
    assert memory.content == "Use ruff for linting."
    assert memory.type == MemoryType.CONVENTION
    assert memory.session_id == "sess-1"


# ---------------------------------------------------------------------------
# retain — dedup
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_retain_duplicate_same_type_returns_same_ref_id() -> None:
    """Retaining identical content + type returns the existing ref_id."""
    svc, _, _ = _make_service()
    content = "Always write type annotations."
    ref1 = svc.retain(content, MemoryType.CONVENTION)
    ref2 = svc.retain(content, MemoryType.CONVENTION)
    assert ref1 == ref2


@pytest.mark.unit
def test_retain_duplicate_updates_session_and_timestamp() -> None:
    """Dedup path updates session_id and timestamp on the existing memory."""
    svc, _, _ = _make_service()
    content = "Use PostgreSQL."
    ref1 = svc.retain(content, MemoryType.DECISION, session_id="session-A")
    memory_before = svc.get(ref1)
    assert memory_before is not None
    ts_before = memory_before.timestamp

    ref2 = svc.retain(content, MemoryType.DECISION, session_id="session-B")
    assert ref1 == ref2

    memory_after = svc.get(ref2)
    assert memory_after is not None
    assert memory_after.session_id == "session-B"
    assert memory_after.timestamp >= ts_before


@pytest.mark.unit
def test_retain_same_content_different_type_returns_different_ref_id() -> None:
    """Same content + different type is a separate memory (ADR-5 widened key)."""
    svc, _, _ = _make_service()
    content = "Use async/await everywhere."
    ref_decision = svc.retain(content, MemoryType.DECISION)
    ref_convention = svc.retain(content, MemoryType.CONVENTION)
    assert ref_decision != ref_convention


# ---------------------------------------------------------------------------
# retain — CODE chunking
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_retain_code_with_chunker_preserves_get_round_trip() -> None:
    """get(retain(code)) must return the full original file, not just one chunk.

    retain(CODE) stores the original content as the canonical record and also
    indexes each chunk for recall() granularity.  The returned ref_id points
    to the original so callers can always retrieve what they submitted.
    """
    from unittest.mock import MagicMock

    stub_chunker = MagicMock()
    stub_chunker.chunk.return_value = ["chunk one content", "chunk two content"]

    original = "original code content"
    svc, _, _ = _make_service(chunker=stub_chunker)
    ref_id = svc.retain(original, MemoryType.CODE, source="foo.py")

    stub_chunker.chunk.assert_called_once_with(original, {"source": "foo.py"})
    # get(ref_id) must return the original, not a chunk
    memory = svc.get(ref_id)
    assert memory is not None
    assert memory.content == original
    # original + 2 distinct chunks = 3 records total
    assert svc.count() == 3


@pytest.mark.unit
def test_retain_code_single_chunk_also_preserves_get_round_trip() -> None:
    """Single-chunk code: get(retain(code)) still returns the original file.

    The chunk is indexed separately for recall(); the canonical ref_id points
    to the full original source.
    """
    from unittest.mock import MagicMock

    stub_chunker = MagicMock()
    stub_chunker.chunk.return_value = ["def foo(): pass"]  # stripped of header

    original = "# module comment\ndef foo(): pass"
    svc, _, _ = _make_service(chunker=stub_chunker)
    ref_id = svc.retain(original, MemoryType.CODE, source="foo.py")

    memory = svc.get(ref_id)
    assert memory is not None
    assert memory.content == original  # full original, not the stripped chunk
    assert svc.count() == 2  # original + one distinct chunk


@pytest.mark.unit
def test_retain_code_without_chunker_stores_single_record() -> None:
    """retain(CODE) with no chunker injected behaves like any other type."""
    svc, _, _ = _make_service()  # no chunker
    ref_id = svc.retain("def foo(): pass", MemoryType.CODE, source="foo.py")
    assert isinstance(ref_id, str)
    assert svc.count() == 1


@pytest.mark.unit
def test_forget_code_deletes_canonical_and_all_chunks() -> None:
    """forget(retain(CODE)) must remove the canonical record AND every chunk record.

    Regression: retain(CODE) with a chunker stores original + N chunks.
    forget() previously only deleted the canonical ref_id, leaving N orphaned
    chunk records that still surfaced in recall().
    """
    stub_chunker = MagicMock()
    stub_chunker.chunk.return_value = ["def foo(): pass", "def bar(): pass"]

    svc, _, _ = _make_service(chunker=stub_chunker)
    ref_id = svc.retain("def foo(): pass\ndef bar(): pass", MemoryType.CODE, source="ab.py")

    # canonical + 2 chunks = 3 records
    assert svc.count() == 3

    deleted = svc.forget(ref_id)
    assert deleted is True
    assert svc.count() == 0
    assert svc.get(ref_id) is None


# ---------------------------------------------------------------------------
# recall
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_recall_returns_artifact_refs_not_memory() -> None:
    """recall() returns ArtifactRef objects, not full Memory objects."""
    from memkernel.core.models import ArtifactRef

    svc, _, _ = _make_service()
    svc.retain("Use Python 3.11 features.", MemoryType.CONVENTION)
    results = svc.recall("Python features")
    for r in results:
        assert isinstance(r, ArtifactRef)
        # ArtifactRef has no `content` attribute
        assert not hasattr(r, "content")


@pytest.mark.unit
def test_recall_type_filter_returns_only_matching_type() -> None:
    svc, _, _ = _make_service()
    svc.retain("convention text about ruff", MemoryType.CONVENTION)
    svc.retain("decision text about ruff linting choices", MemoryType.DECISION)

    results = svc.recall("ruff", type=MemoryType.CONVENTION)
    for r in results:
        assert r.type == MemoryType.CONVENTION


@pytest.mark.unit
def test_recall_session_filter_returns_only_matching_session() -> None:
    svc, _, _ = _make_service()
    svc.retain("session A memory content", MemoryType.EPISODE, session_id="sess-A")
    svc.retain("session B memory content", MemoryType.EPISODE, session_id="sess-B")

    results = svc.recall("memory content", session_id="sess-A")
    for r in results:
        # Each ArtifactRef must correspond to a memory from sess-A
        full = svc.get(r.ref_id)
        assert full is not None
        assert full.session_id == "sess-A"


@pytest.mark.unit
def test_recall_top_k_zero_returns_empty_list() -> None:
    """recall(top_k=0) must return [] not fall back to the settings default.

    `top_k or default` treats 0 as falsy and silently returns `default` results.
    The fix uses an explicit None check so zero is honoured as a literal request
    for no results.
    """
    svc, _, _ = _make_service()
    svc.retain("some convention content", MemoryType.CONVENTION)
    results = svc.recall("convention content", top_k=0)
    assert results == []


@pytest.mark.unit
def test_recall_expired_episodes_do_not_crowd_out_live_results() -> None:
    """Expired episodes must not suppress live results regardless of corpus size.

    Regression for the bounded fetch-window bug: a fixed max_fetch cap
    (desired_k * 20) caused recall(top_k=1) to return an empty list when 20+
    expired episodes all ranked above the single live result.  The fix drops
    the cap and relies on store_exhausted alone for loop termination.
    """
    from datetime import timedelta
    from uuid import uuid4 as _uuid4

    # 20 expired episodes + 1 live decision — matches the exact reproducer
    n_expired = 20
    settings = _make_settings(episode_ttl_days=30, search_top_k=1)
    svc, store, sparse = _make_service(settings=settings)

    embedding = MockEmbedding()
    old_ts = (datetime.now(UTC) - timedelta(days=60)).isoformat()

    for i in range(n_expired):
        ref_id = str(_uuid4())
        content = f"postgres expired episode content {i}"
        vec = embedding.embed([content])[0]
        store.upsert(
            ref_id=ref_id,
            content=content,
            embedding=vec,
            metadata={
                "project_id": settings.project_id,
                "session_id": "default",
                "timestamp": old_ts,
                "type": MemoryType.EPISODE.value,
                "source": "test",
                "hash": f"deadbeef{i:04x}",
                "token_count": 5,
                "checkpoint": False,
            },
        )
        # Mirror into sparse index so the full hybrid ranking path is exercised
        sparse.add(ref_id, content)

    # Insert one live decision (never expires)
    live_ref = svc.retain("use postgres as the primary database", MemoryType.DECISION)

    # With top_k=1, the live decision must be returned even though 20 expired
    # episodes fill the initial fetch windows.
    results = svc.recall("postgres", top_k=1)
    assert len(results) == 1
    assert results[0].ref_id == live_ref


# ---------------------------------------------------------------------------
# get
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_get_returns_full_memory() -> None:
    svc, _, _ = _make_service()
    ref_id = svc.retain("Full content here.", MemoryType.CODE)
    memory = svc.get(ref_id)
    assert memory is not None
    assert memory.content == "Full content here."
    assert memory.ref_id == ref_id


@pytest.mark.unit
def test_get_returns_none_for_missing_ref_id() -> None:
    svc, _, _ = _make_service()
    assert svc.get("nonexistent-ref-id") is None


# ---------------------------------------------------------------------------
# forget
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_forget_removes_from_both_stores() -> None:
    svc, store, sparse = _make_service()
    ref_id = svc.retain("Forget me please.", MemoryType.EPISODE)

    deleted = svc.forget(ref_id)
    assert deleted is True

    # Vector store reports None
    assert svc.get(ref_id) is None

    # BM25 index no longer contains the doc
    assert len(sparse) == 0


@pytest.mark.unit
def test_forget_returns_false_for_nonexistent_ref_id() -> None:
    svc, _, _ = _make_service()
    assert svc.forget("does-not-exist") is False


# ---------------------------------------------------------------------------
# BM25 failure during retain sets needs_rebuild
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_bm25_failure_on_retain_sets_needs_rebuild() -> None:
    """If BM25 add() raises, MemoryService marks the index for rebuild."""
    settings = _make_settings()
    store = ChromaVectorStore(settings, client=chromadb.EphemeralClient())
    embedding = MockEmbedding()

    # Mock sparse index whose add() always raises
    mock_sparse = MagicMock(spec=BM25Index)
    mock_sparse.add.side_effect = RuntimeError("simulated BM25 failure")
    mock_sparse.needs_rebuild = False  # initial state

    search_svc = HybridSearchService(store, embedding, mock_sparse, settings)
    svc = MemoryService(store, embedding, mock_sparse, search_svc, settings)

    # Should not raise — BM25 failure is non-fatal
    ref_id = svc.retain("Test BM25 failure resilience.", MemoryType.CONVENTION)
    assert isinstance(ref_id, str)

    # mark_needs_rebuild should have been called
    mock_sparse.mark_needs_rebuild.assert_called_once()


# ---------------------------------------------------------------------------
# BM25 failure during forget sets needs_rebuild
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_bm25_failure_on_forget_canonical_sets_needs_rebuild() -> None:
    """If BM25 remove() raises during forget(), the service marks the index for rebuild.

    The vector-store deletion must still succeed — BM25 failure is non-fatal.
    """
    settings = _make_settings()
    store = ChromaVectorStore(settings, client=chromadb.EphemeralClient())
    embedding = MockEmbedding()

    mock_sparse = MagicMock(spec=BM25Index)
    mock_sparse.add.return_value = None  # retain succeeds
    mock_sparse.remove.side_effect = RuntimeError("simulated BM25 remove failure")
    mock_sparse.needs_rebuild = False

    search_svc = HybridSearchService(store, embedding, mock_sparse, settings)
    svc = MemoryService(store, embedding, mock_sparse, search_svc, settings)

    ref_id = svc.retain("Content to forget.", MemoryType.CONVENTION)

    # Should not raise — BM25 failure is non-fatal
    deleted = svc.forget(ref_id)
    assert deleted is True
    assert svc.get(ref_id) is None
    mock_sparse.mark_needs_rebuild.assert_called()


@pytest.mark.unit
def test_bm25_failure_on_forget_chunk_sets_needs_rebuild() -> None:
    """If BM25 remove() raises for a chunk ref during forget(), service marks rebuild.

    Covers the chunk-deletion loop in forget() (services.py lines 214-216).
    Vector-store deletions for both chunks and canonical must still succeed.
    """
    stub_chunker = MagicMock()
    stub_chunker.chunk.return_value = ["chunk one content", "chunk two content"]

    settings = _make_settings()
    store = ChromaVectorStore(settings, client=chromadb.EphemeralClient())
    embedding = MockEmbedding()

    mock_sparse = MagicMock(spec=BM25Index)
    mock_sparse.add.return_value = None  # retain succeeds
    mock_sparse.remove.side_effect = RuntimeError("simulated BM25 remove failure")
    mock_sparse.needs_rebuild = False

    search_svc = HybridSearchService(store, embedding, mock_sparse, settings)
    svc = MemoryService(store, embedding, mock_sparse, search_svc, settings, chunker=stub_chunker)

    ref_id = svc.retain("original code content", MemoryType.CODE, source="foo.py")
    # canonical + 2 chunks stored in vector store
    assert store.count() == 3

    deleted = svc.forget(ref_id)
    assert deleted is True
    assert svc.get(ref_id) is None
    assert store.count() == 0  # all records removed from vector store
    mock_sparse.mark_needs_rebuild.assert_called()


# ---------------------------------------------------------------------------
# recall() self-heals BM25 when needs_rebuild is set
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_recall_triggers_rebuild_when_needs_rebuild_set() -> None:
    """recall() calls rebuild_sparse_index() when needs_rebuild is True.

    Covers services.py line 164 — the self-heal path that was previously
    unreachable in tests.
    """
    svc, store, sparse = _make_service()
    svc.retain("rebuild trigger content", MemoryType.DECISION)

    # Simulate index loss and set the rebuild flag
    sparse.rebuild([])
    sparse.mark_needs_rebuild()
    assert len(sparse) == 0
    assert sparse.needs_rebuild is True

    # recall() must self-heal before searching
    svc.recall("rebuild trigger content")

    assert sparse.needs_rebuild is False
    assert len(sparse) == 1  # repopulated from vector store


# ---------------------------------------------------------------------------
# rebuild_sparse_index
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_rebuild_sparse_index_repopulates_from_vector_store() -> None:
    """rebuild_sparse_index() re-adds all docs from ChromaDB into BM25."""
    svc, store, sparse = _make_service()

    svc.retain("First document content.", MemoryType.DECISION)
    svc.retain("Second document content.", MemoryType.CONVENTION)

    # Clear BM25 manually to simulate loss
    sparse.rebuild([])
    assert len(sparse) == 0

    svc.rebuild_sparse_index()
    assert len(sparse) == 2


# ---------------------------------------------------------------------------
# checkpoint flag — 10a/10b
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_retain_checkpoint_flag_stored_in_memory() -> None:
    """retain(checkpoint=True) must persist checkpoint=True on the Memory record."""
    svc, _, _ = _make_service()
    ref_id = svc.retain(
        "SESSION CHECKPOINT — decisions so far",
        MemoryType.EPISODE,
        checkpoint=True,
    )
    memory = svc.get(ref_id)
    assert memory is not None
    assert memory.checkpoint is True


@pytest.mark.unit
def test_retain_checkpoint_defaults_to_false() -> None:
    """retain() without checkpoint flag stores checkpoint=False."""
    svc, _, _ = _make_service()
    ref_id = svc.retain("Regular episode content", MemoryType.EPISODE)
    memory = svc.get(ref_id)
    assert memory is not None
    assert memory.checkpoint is False


@pytest.mark.unit
def test_recall_checkpoint_only_filters_to_checkpoints() -> None:
    """recall(checkpoint_only=True) must return only checkpoint memories."""
    svc, _, _ = _make_service()
    cp_ref = svc.retain("SESSION CHECKPOINT content", MemoryType.EPISODE, checkpoint=True)
    svc.retain("Regular decision content", MemoryType.DECISION, checkpoint=False)
    svc.retain("Another episode not a checkpoint", MemoryType.EPISODE, checkpoint=False)

    results = svc.recall("content", checkpoint_only=True, top_k=10)
    ref_ids = {r.ref_id for r in results}
    assert cp_ref in ref_ids, "checkpoint memory must be returned"
    # Every returned memory must be a checkpoint
    for r in results:
        full = svc.get(r.ref_id)
        assert full is not None
        assert full.checkpoint is True, f"non-checkpoint memory {r.ref_id} leaked into checkpoint_only results"


@pytest.mark.unit
def test_recall_without_checkpoint_only_returns_all() -> None:
    """recall() without checkpoint_only=True returns checkpoints and regular memories."""
    svc, _, _ = _make_service()
    cp_ref = svc.retain("SESSION CHECKPOINT content", MemoryType.EPISODE, checkpoint=True)
    reg_ref = svc.retain("Regular decision content", MemoryType.DECISION, checkpoint=False)

    results = svc.recall("content", top_k=10)
    ref_ids = {r.ref_id for r in results}
    assert cp_ref in ref_ids
    assert reg_ref in ref_ids


# ── supersede (memkernel-0-6 FR-017) ──────────────────────────────────────────


def test_supersede_marks_the_old_record_and_changes_nothing_else() -> None:
    svc, _, _ = _make_service()
    old = svc.retain("Deploys happen on Fridays", MemoryType.CONVENTION, tags=["ops"])
    new = svc.retain("Deploys happen on Tuesdays", MemoryType.CONVENTION)
    before = svc.get(old, touch=False)

    assert svc.supersede(old, new) is True

    after = svc.get(old, touch=False)
    assert before is not None and after is not None and after.superseded_by == new
    assert (after.content, after.type, after.tier, after.tags) == (
        before.content,
        before.type,
        before.tier,
        before.tags,
    )
    assert old not in {m.ref_id for m in svc.list_memories()}  # no longer current
    assert svc.supersede(old, new) is False  # idempotent


@pytest.mark.parametrize("case", ["unknown", "missing replacement", "self", "already superseded by another"])
def test_supersede_refuses_and_changes_nothing(case: str) -> None:
    svc, _, _ = _make_service()
    old = svc.retain("Deploys happen on Fridays", MemoryType.CONVENTION)
    new = svc.retain("Deploys happen on Tuesdays", MemoryType.CONVENTION)
    other = svc.retain("Deploys happen on Mondays", MemoryType.CONVENTION)
    svc.supersede(other, new) if case == "already superseded by another" else None
    target, by = {
        "unknown": ("mem-unknown", new),
        "missing replacement": (old, "mem-unknown"),
        "self": (old, old),
        "already superseded by another": (other, old),
    }[case]
    before = {m.ref_id: m.superseded_by for m in svc.list_memories(include_superseded=True)}

    with pytest.raises(ValueError):
        svc.supersede(target, by)

    assert {m.ref_id: m.superseded_by for m in svc.list_memories(include_superseded=True)} == before


def test_supersede_refuses_a_record_of_another_project() -> None:
    svc, _, _ = _make_service()
    foreign, _, _ = _make_service(_make_settings(project_id=f"other-{uuid.uuid4().hex[:8]}"))
    elsewhere = foreign.retain("A memory of another project", MemoryType.FACT)
    mine = svc.retain("A memory of this project", MemoryType.FACT)

    with pytest.raises(ValueError, match="not a memory in this store"):
        svc.supersede(elsewhere, mine)

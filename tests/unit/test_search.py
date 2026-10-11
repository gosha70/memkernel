"""Unit tests for HybridSearchService and its helper functions."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import chromadb
import pytest

from memkernel.config import MemKernelSettings
from memkernel.core.models import MemoryType, SearchQuery, SearchResult
from memkernel.retrieval.search import (
    HybridSearchService,
    _build_where_filter,
    _metadata_matches,
    filter_sparse_results,
    include_document_parts,
    rrf_fuse,
)
from memkernel.retrieval.sparse import BM25Index
from memkernel.storage.chroma import ChromaVectorStore
from tests.conftest import MockEmbedding

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_settings(**overrides: Any) -> MemKernelSettings:
    base: dict[str, Any] = {
        "project_id": "test",
        "default_session_id": "s1",
        "rrf_k": 60,
        "search_top_k": 5,
        "preview_length": 200,
        "episode_ttl_days": 30,
    }
    base.update(overrides)
    return MemKernelSettings(**base)


def _make_store(settings: MemKernelSettings) -> ChromaVectorStore:
    """ChromaDB in-memory store (EphemeralClient)."""
    return ChromaVectorStore(settings, client=chromadb.EphemeralClient())


def _insert(
    store: ChromaVectorStore,
    sparse: BM25Index,
    embedding: MockEmbedding,
    ref_id: str,
    content: str,
    memory_type: MemoryType = MemoryType.DECISION,
    session_id: str = "s1",
    checkpoint: bool = False,
) -> None:
    emb = embedding.embed([content])[0]
    metadata = {
        "project_id": "test",
        "session_id": session_id,
        "timestamp": datetime.now(UTC).isoformat(),
        "type": memory_type.value,
        "source": "",
        "hash": f"hash_{ref_id}",
        "token_count": max(1, len(content) // 4),
        "checkpoint": checkpoint,
    }
    store.upsert(ref_id=ref_id, content=content, embedding=emb, metadata=metadata)
    sparse.add(ref_id, content)


# ---------------------------------------------------------------------------
# rrf_fuse
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_rrf_doc_in_both_lists_scores_higher() -> None:
    """A doc appearing in both dense and sparse lists should outscore a doc in only one."""
    k = 60
    both = SearchResult(ref_id="both", score=0.9, rank=1)
    only_dense = SearchResult(ref_id="dense_only", score=0.8, rank=2)
    only_sparse = SearchResult(ref_id="sparse_only", score=0.7, rank=1)

    fused = dict(rrf_fuse(k, [both, only_dense], [both, only_sparse]))

    assert fused["both"] > fused["dense_only"]
    assert fused["both"] > fused["sparse_only"]


@pytest.mark.unit
def test_rrf_numerical_values() -> None:
    """RRF score = 1/(k+rank).  Verify exact arithmetic for a known input."""
    k = 60
    result = SearchResult(ref_id="doc1", score=1.0, rank=1)
    fused = dict(rrf_fuse(k, [result]))

    expected = 1.0 / (k + 1)
    assert abs(fused["doc1"] - expected) < 1e-9


@pytest.mark.unit
def test_rrf_two_lists_same_doc() -> None:
    """Doc at rank 1 in two lists: score == 2 * 1/(k+1)."""
    k = 60
    r1 = SearchResult(ref_id="d", score=1.0, rank=1)
    r2 = SearchResult(ref_id="d", score=0.9, rank=1)
    fused = dict(rrf_fuse(k, [r1], [r2]))

    expected = 2.0 / (k + 1)
    assert abs(fused["d"] - expected) < 1e-9


@pytest.mark.unit
def test_rrf_empty_lists() -> None:
    """Empty lists produce empty fused output."""
    assert rrf_fuse(60, [], []) == []


# ---------------------------------------------------------------------------
# _build_where_filter
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_where_filter_no_conditions() -> None:
    q = SearchQuery(query_text="x")
    assert _build_where_filter(q) is None


@pytest.mark.unit
def test_where_filter_type_only() -> None:
    q = SearchQuery(query_text="x", type_filter=MemoryType.DECISION)
    assert _build_where_filter(q) == {"type": "decision"}


@pytest.mark.unit
def test_where_filter_session_only() -> None:
    q = SearchQuery(query_text="x", session_id_filter="sess-42")
    assert _build_where_filter(q) == {"session_id": "sess-42"}


@pytest.mark.unit
def test_where_filter_checkpoint_only_flag() -> None:
    q = SearchQuery(query_text="x", checkpoint_only=True)
    assert _build_where_filter(q) == {"checkpoint": True}


@pytest.mark.unit
def test_where_filter_type_and_session() -> None:
    q = SearchQuery(query_text="x", type_filter=MemoryType.CODE, session_id_filter="s9")
    result = _build_where_filter(q)
    assert result == {"$and": [{"type": "code"}, {"session_id": "s9"}]}


@pytest.mark.unit
def test_where_filter_all_three() -> None:
    q = SearchQuery(
        query_text="x",
        type_filter=MemoryType.EPISODE,
        session_id_filter="s1",
        checkpoint_only=True,
    )
    result = _build_where_filter(q)
    assert result == {
        "$and": [
            {"type": "episode"},
            {"session_id": "s1"},
            {"checkpoint": True},
        ]
    }


# ---------------------------------------------------------------------------
# Stale BM25 entry handling
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_stale_bm25_entry_skipped() -> None:
    """filter_sparse_results silently skips ref_ids not in the vector store."""
    settings = _make_settings()
    store = _make_store(settings)
    embedding = MockEmbedding()

    # Insert one doc in both stores
    _insert(store, BM25Index(), embedding, "real-1", "real document content")

    # Sparse results include a stale ref_id that does not exist in the store
    sparse_results = [
        SearchResult(ref_id="real-1", score=1.0, rank=1),
        SearchResult(ref_id="stale-999", score=0.9, rank=2),
    ]

    filtered = filter_sparse_results(sparse_results, None, store)

    assert len(filtered) == 1
    assert filtered[0].ref_id == "real-1"


# ---------------------------------------------------------------------------
# End-to-end search
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_e2e_search_returns_expected_results() -> None:
    """Insert two docs; the one semantically closer to the query ranks first."""
    settings = _make_settings()
    store = _make_store(settings)
    sparse = BM25Index()
    embedding = MockEmbedding()

    _insert(store, sparse, embedding, "id-alpha", "Use PostgreSQL for persistence decisions")
    _insert(store, sparse, embedding, "id-beta", "Cookie recipe with chocolate chips")

    service = HybridSearchService(store, embedding, sparse, settings)
    query = SearchQuery(query_text="PostgreSQL persistence", top_k=2)
    results = service.search(query)

    ref_ids = [r.ref_id for r in results]
    assert "id-alpha" in ref_ids
    # alpha should outrank beta
    assert ref_ids.index("id-alpha") < ref_ids.index("id-beta") if "id-beta" in ref_ids else True


@pytest.mark.unit
def test_e2e_search_respects_top_k() -> None:
    """search() never returns more than top_k results."""
    settings = _make_settings(search_top_k=2)
    store = _make_store(settings)
    sparse = BM25Index()
    embedding = MockEmbedding()

    for i in range(5):
        _insert(store, sparse, embedding, f"id-{i}", f"memory document number {i} foo bar baz")

    service = HybridSearchService(store, embedding, sparse, settings)
    results = service.search(SearchQuery(query_text="memory document", top_k=2))
    assert len(results) <= 2


@pytest.mark.unit
def test_filtered_sparse_with_type_filter() -> None:
    """Filtered sparse search: only memories matching the type filter pass through."""
    settings = _make_settings()
    store = _make_store(settings)
    sparse = BM25Index()
    embedding = MockEmbedding()

    _insert(store, sparse, embedding, "dec-1", "architecture decision doc", MemoryType.DECISION)
    _insert(store, sparse, embedding, "ep-1", "episode memory about architecture", MemoryType.EPISODE)

    where = {"type": "decision"}
    sparse_results = [
        SearchResult(ref_id="dec-1", score=1.0, rank=1),
        SearchResult(ref_id="ep-1", score=0.9, rank=2),
    ]

    filtered = filter_sparse_results(sparse_results, where, store)

    assert len(filtered) == 1
    assert filtered[0].ref_id == "dec-1"
    assert filtered[0].rank == 1  # re-ranked from 1


@pytest.mark.unit
def test_search_top_k_zero_does_not_crash() -> None:
    """search() with top_k=0 must not pass n_results=0 to ChromaDB."""
    settings = _make_settings()
    store = _make_store(settings)
    sparse = BM25Index()
    embedding = MockEmbedding()

    _insert(store, sparse, embedding, "id-1", "some content")

    service = HybridSearchService(store, embedding, sparse, settings)
    # top_k=0 previously caused over_fetch=0 → ChromaDB raised an exception
    results = service.search(SearchQuery(query_text="some content", top_k=0))
    assert results == []


# ---------------------------------------------------------------------------
# include_document_parts / document_part matching
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_include_document_parts_wraps_filter_in_or_and_keeps_none() -> None:
    assert include_document_parts(None) is None
    assert include_document_parts({"session_id": "s1"}) == {"$or": [{"session_id": "s1"}, {"document_part": True}]}


@pytest.mark.unit
def test_metadata_matches_lets_document_parts_through_or_filters() -> None:
    from datetime import UTC, datetime

    from memkernel.core.models import DOCUMENT_CHUNK_TAG, Memory, MemoryType

    def mem(tags: list[str], session: str) -> Memory:
        return Memory(
            ref_id="r",
            content="c",
            type=MemoryType.DOCUMENT,
            project_id="p",
            session_id=session,
            timestamp=datetime.now(UTC),
            content_hash="h",
            token_count=1,
            tags=tags,
        )

    where = include_document_parts({"session_id": "s1"})
    assert where is not None
    assert _metadata_matches(mem([DOCUMENT_CHUNK_TAG], "default"), where) is True
    assert _metadata_matches(mem([], "s1"), where) is True
    assert _metadata_matches(mem([], "s2"), where) is False
    assert _metadata_matches(mem([], "s2"), {"document_part": True}) is False

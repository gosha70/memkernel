"""Unit tests for ChromaVectorStore using in-memory ChromaDB."""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from typing import Any, cast

import chromadb
import pytest

from memkernel.config import MemKernelSettings
from memkernel.core.models import MemoryType
from memkernel.storage.chroma import ChromaVectorStore

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DIM = 8


def _make_settings(project_id: str | None = None, **overrides: Any) -> MemKernelSettings:
    base: dict[str, Any] = {"project_id": project_id or f"test-{uuid.uuid4().hex}"}
    base.update(overrides)
    return MemKernelSettings(**cast("Any", base))


def _unit_embedding(text: str, dim: int = _DIM) -> list[float]:
    """Deterministic unit-norm embedding derived from content hash."""
    raw = [b / 255.0 for b in hashlib.sha256(text.encode()).digest()[:dim]]
    norm = sum(x * x for x in raw) ** 0.5
    return [x / norm if norm > 0 else 0.0 for x in raw]


def _base_metadata(
    *,
    project_id: str = "test-project",
    session_id: str = "sess-1",
    memory_type: MemoryType = MemoryType.DECISION,
    content_hash: str = "abc123",
    token_count: int = 10,
    source: str = "test",
    checkpoint: bool = False,
) -> dict[str, object]:
    return {
        "project_id": project_id,
        "session_id": session_id,
        "type": memory_type,
        "hash": content_hash,
        "token_count": token_count,
        "source": source,
        "timestamp": datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
        "checkpoint": checkpoint,
    }


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def store() -> ChromaVectorStore:
    # Use a unique project_id per test so each test gets its own collection
    # in the shared EphemeralClient in-memory store.
    settings = _make_settings()
    client = chromadb.EphemeralClient()
    return ChromaVectorStore(settings, client=client)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize("persist_path", ["", "   "])
def test_empty_persist_path_uses_in_memory_client(persist_path: str) -> None:
    """Blank persist paths fall back to ChromaDB's in-memory client."""
    settings = _make_settings(chroma_persist_path=persist_path)
    blank_path_store = ChromaVectorStore(settings)

    content = "Use an in-memory Chroma client in tests."
    blank_path_store.upsert(
        "ref-blank-path",
        content,
        _unit_embedding(content),
        _base_metadata(content_hash="blank-path-hash"),
    )

    memory = blank_path_store.get_by_id("ref-blank-path")
    assert memory is not None
    assert memory.content == content


@pytest.mark.unit
def test_upsert_get_by_id_round_trip(store: ChromaVectorStore) -> None:
    """upsert then get_by_id returns a Memory with all fields intact."""
    content = "Use ADR-5 for deduplication."
    ref_id = "ref-001"
    metadata = _base_metadata(
        content_hash="hash-adr5",
        token_count=7,
        source="adr",
    )

    store.upsert(ref_id, content, _unit_embedding(content), metadata)
    memory = store.get_by_id(ref_id)

    assert memory is not None
    assert memory.ref_id == ref_id
    assert memory.content == content
    assert memory.type == MemoryType.DECISION
    assert memory.project_id == "test-project"
    assert memory.session_id == "sess-1"
    assert memory.content_hash == "hash-adr5"
    assert memory.token_count == 7
    assert memory.source == "adr"
    assert memory.checkpoint is False


@pytest.mark.unit
def test_search_dense_returns_results_ordered_by_score(store: ChromaVectorStore) -> None:
    """search_dense returns results with descending similarity score."""
    query = "architectural decision"
    docs = {
        "ref-a": "Use ports and adapters for architecture",
        "ref-b": "The cat sat on the mat",
        "ref-c": "Architectural patterns and design decisions",
    }
    for ref_id, content in docs.items():
        store.upsert(ref_id, content, _unit_embedding(content), _base_metadata(content_hash=ref_id))

    results = store.search_dense(_unit_embedding(query), top_k=3)

    assert len(results) == 3
    scores = [r.score for r in results]
    assert scores == sorted(scores, reverse=True), "Results must be ordered by descending score"
    ranks = [r.rank for r in results]
    assert ranks == [1, 2, 3], "Ranks must be 1-based consecutive"


@pytest.mark.unit
def test_search_dense_with_where_filter(store: ChromaVectorStore) -> None:
    """search_dense with where filter only returns matching documents."""
    store.upsert(
        "ref-decision",
        "Use ChromaDB for vector storage",
        _unit_embedding("Use ChromaDB for vector storage"),
        _base_metadata(memory_type=MemoryType.DECISION, content_hash="h1"),
    )
    store.upsert(
        "ref-episode",
        "Session started at 10am",
        _unit_embedding("Session started at 10am"),
        _base_metadata(memory_type=MemoryType.EPISODE, content_hash="h2"),
    )

    results = store.search_dense(
        _unit_embedding("storage"),
        top_k=5,
        where={"type": "decision"},
    )

    assert all(r.ref_id == "ref-decision" for r in results)


@pytest.mark.unit
def test_delete_removes_entry(store: ChromaVectorStore) -> None:
    """After delete, get_by_id returns None."""
    ref_id = "ref-del"
    store.upsert(ref_id, "to be deleted", _unit_embedding("to be deleted"), _base_metadata())

    existed = store.delete(ref_id)

    assert existed is True
    assert store.get_by_id(ref_id) is None


@pytest.mark.unit
def test_delete_returns_false_for_missing(store: ChromaVectorStore) -> None:
    """delete on a non-existent ref_id returns False."""
    result = store.delete("does-not-exist")
    assert result is False


@pytest.mark.unit
def test_find_by_hash_returns_existing_entry(store: ChromaVectorStore) -> None:
    """find_by_hash returns the stored memory when hash+type match."""
    content = "Always use UTC timestamps."
    ref_id = "ref-hash-1"
    content_hash = "sha256-utc"
    store.upsert(
        ref_id,
        content,
        _unit_embedding(content),
        _base_metadata(
            memory_type=MemoryType.CONVENTION,
            content_hash=content_hash,
        ),
    )

    found = store.find_by_hash(content_hash, "convention")

    assert found is not None
    assert found.ref_id == ref_id
    assert found.content_hash == content_hash


@pytest.mark.unit
def test_find_by_hash_returns_none_for_wrong_type(store: ChromaVectorStore) -> None:
    """find_by_hash returns None when hash matches but type differs."""
    content = "Typed wrong."
    content_hash = "sha256-type-mismatch"
    store.upsert(
        "ref-type-mismatch",
        content,
        _unit_embedding(content),
        _base_metadata(memory_type=MemoryType.CONVENTION, content_hash=content_hash),
    )

    result = store.find_by_hash(content_hash, "decision")
    assert result is None


@pytest.mark.unit
def test_find_by_hash_returns_none_for_missing_hash(store: ChromaVectorStore) -> None:
    """find_by_hash returns None when the hash does not exist."""
    result = store.find_by_hash("nonexistent-hash", "decision")
    assert result is None


@pytest.mark.unit
def test_update_metadata_merges_keys(store: ChromaVectorStore) -> None:
    """update_metadata overwrites only the specified key; immutable fields are preserved."""
    ref_id = "ref-update"
    original_hash = "orig-hash"
    original_project = "test-project"
    original_token_count = 42
    content = "merge test content"

    store.upsert(
        ref_id,
        content,
        _unit_embedding(content),
        _base_metadata(
            content_hash=original_hash,
            project_id=original_project,
            token_count=original_token_count,
            session_id="old-session",
        ),
    )

    store.update_metadata(ref_id, {"session_id": "new-session"})

    updated = store.get_by_id(ref_id)
    assert updated is not None
    assert updated.session_id == "new-session"
    # Immutable fields must survive the merge
    assert updated.content_hash == original_hash
    assert updated.project_id == original_project
    assert updated.token_count == original_token_count
    assert updated.source == "test"
    assert updated.type == MemoryType.DECISION


@pytest.mark.unit
def test_count_returns_correct_number(store: ChromaVectorStore) -> None:
    """count reflects the exact number of upserted entries."""
    assert store.count() == 0

    for i in range(3):
        c = f"memory {i}"
        store.upsert(f"ref-{i}", c, _unit_embedding(c), _base_metadata(content_hash=f"h{i}"))

    assert store.count() == 3


@pytest.mark.unit
def test_list_all_returns_all_memories(store: ChromaVectorStore) -> None:
    """list_all returns every stored memory."""
    ref_ids = {"ref-x", "ref-y", "ref-z"}
    for ref_id in ref_ids:
        c = f"content {ref_id}"
        store.upsert(ref_id, c, _unit_embedding(c), _base_metadata(content_hash=ref_id))

    memories = store.list_all()

    assert {m.ref_id for m in memories} == ref_ids


@pytest.mark.unit
def test_list_all_with_where_filter_returns_subset(store: ChromaVectorStore) -> None:
    """list_all with where filter returns only matching memories."""
    store.upsert(
        "ref-keep",
        "keep this",
        _unit_embedding("keep this"),
        _base_metadata(memory_type=MemoryType.CODE, content_hash="h-keep"),
    )
    store.upsert(
        "ref-skip",
        "skip this",
        _unit_embedding("skip this"),
        _base_metadata(memory_type=MemoryType.EPISODE, content_hash="h-skip"),
    )

    results = store.list_all(where={"type": "code"})

    assert len(results) == 1
    assert results[0].ref_id == "ref-keep"

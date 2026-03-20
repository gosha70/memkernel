"""Integration tests for ChromaVectorStore — persistence across client restarts."""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import chromadb
import pytest

if TYPE_CHECKING:
    from pathlib import Path

from memkernel.config import MemKernelSettings
from memkernel.core.models import MemoryType
from memkernel.core.services import MemoryService
from memkernel.retrieval.search import HybridSearchService
from memkernel.retrieval.sparse import BM25Index
from memkernel.storage.chroma import ChromaVectorStore
from tests.conftest import MockEmbedding


def _unit_embedding(text: str, dim: int = 8) -> list[float]:
    raw = [b / 255.0 for b in hashlib.sha256(text.encode()).digest()[:dim]]
    norm = sum(x * x for x in raw) ** 0.5
    return [x / norm if norm > 0 else 0.0 for x in raw]


def _make_settings(project_id: str | None = None, **overrides: Any) -> MemKernelSettings:
    base: dict[str, Any] = {"project_id": project_id or f"integ-{uuid.uuid4().hex[:8]}"}
    base.update(overrides)
    return MemKernelSettings(**base)


def _make_service(settings: MemKernelSettings) -> MemoryService:
    store = ChromaVectorStore(settings, client=chromadb.EphemeralClient())
    embedding = MockEmbedding()
    sparse = BM25Index()
    search_svc = HybridSearchService(store, embedding, sparse, settings)
    return MemoryService(store, embedding, sparse, search_svc, settings)


@pytest.mark.integration
def test_data_persists_across_client_restarts(tmp_path: Path) -> None:
    """Upserted data survives a full client teardown and re-open on the same path."""
    chroma_dir = str(tmp_path / "chroma")
    settings = _make_settings()
    ref_id = "persist-ref-001"
    content = "Persisted memory across restarts"
    content_hash = "sha-persist-001"

    # --- First client: write ---
    client_a = chromadb.PersistentClient(path=chroma_dir)
    store_a = ChromaVectorStore(settings, client=client_a)
    store_a.upsert(
        ref_id,
        content,
        _unit_embedding(content),
        {
            "project_id": settings.project_id,
            "session_id": "sess-persist",
            "type": "decision",
            "hash": content_hash,
            "token_count": 5,
            "source": "integration-test",
            "timestamp": datetime(2024, 6, 1, 0, 0, 0, tzinfo=UTC),
            "checkpoint": False,
        },
    )
    assert store_a.get_by_id(ref_id) is not None

    # --- Second client: read from same path ---
    client_b = chromadb.PersistentClient(path=chroma_dir)
    store_b = ChromaVectorStore(settings, client=client_b)
    recovered = store_b.get_by_id(ref_id)

    assert recovered is not None
    assert recovered.ref_id == ref_id
    assert recovered.content == content
    assert recovered.content_hash == content_hash
    assert recovered.project_id == settings.project_id


@pytest.mark.integration
def test_retain_identical_content_returns_same_ref_id() -> None:
    """Retaining identical content+type twice returns the same ref_id (dedup).

    Exercises the full MemoryService → ChromaVectorStore path: the service
    calls find_by_hash on the real adapter and must get back the existing
    ref_id on the second retain rather than creating a new record.
    """
    svc = _make_service(_make_settings())
    content = "Use PostgreSQL as the primary database."

    ref_a = svc.retain(content, MemoryType.DECISION, session_id="sess-1")
    ref_b = svc.retain(content, MemoryType.DECISION, session_id="sess-2")

    assert ref_a == ref_b
    assert svc.count() == 1


@pytest.mark.integration
def test_retain_same_content_different_type_creates_separate_records() -> None:
    """Same content + different type must produce distinct ref_ids."""
    svc = _make_service(_make_settings())
    content = "Use async/await throughout."

    ref_decision = svc.retain(content, MemoryType.DECISION)
    ref_convention = svc.retain(content, MemoryType.CONVENTION)

    assert ref_decision != ref_convention
    assert svc.count() == 2

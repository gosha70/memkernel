"""Unit tests for the FastAPI admin API."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Generator

import chromadb
import pytest
from fastapi.testclient import TestClient

from memkernel.api.app import create_app
from memkernel.config import MemKernelSettings
from memkernel.core.models import MemoryType
from memkernel.core.services import MemoryService
from memkernel.retrieval.search import HybridSearchService
from memkernel.retrieval.sparse import BM25Index
from memkernel.storage.chroma import ChromaVectorStore
from tests.conftest import MockEmbedding


def _make_service() -> MemoryService:
    settings = MemKernelSettings(
        project_id=f"admin-test-{uuid.uuid4().hex[:8]}",
        default_session_id="default",
    )
    store = ChromaVectorStore(settings, client=chromadb.EphemeralClient())
    embedding = MockEmbedding()
    sparse = BM25Index()
    search_svc = HybridSearchService(store, embedding, sparse, settings)
    return MemoryService(store, embedding, sparse, search_svc, settings)


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    svc = _make_service()
    with TestClient(create_app(memory_service=svc)) as c:
        yield c


# ---------------------------------------------------------------------------
# /health
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_health_returns_ok(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "project_id" in data
    assert "collection_count" in data
    assert "memory_count" in data
    assert data["memory_count"] == 0
    assert data["collection_count"] >= 1  # at least this project's collection


@pytest.mark.unit
def test_health_reflects_retained_memories() -> None:
    svc = _make_service()
    svc.retain("a decision", MemoryType.DECISION)
    svc.retain("a convention", MemoryType.CONVENTION)
    with TestClient(create_app(memory_service=svc)) as c:
        response = c.get("/health")
    assert response.json()["memory_count"] == 2


# ---------------------------------------------------------------------------
# /stats
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_stats_empty_store(client: TestClient) -> None:
    response = client.get("/stats")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 0
    assert data["by_type"] == {}
    assert "growth" in data
    assert data["growth"]["last_24h"] == 0
    assert data["growth"]["last_7d"] == 0
    assert data["growth"]["last_30d"] == 0
    assert data["last_recall_ms"] is None


@pytest.mark.unit
def test_stats_by_type_breakdown() -> None:
    svc = _make_service()
    svc.retain("a decision", MemoryType.DECISION)
    svc.retain("a convention", MemoryType.CONVENTION)
    svc.retain("another convention", MemoryType.CONVENTION)

    with TestClient(create_app(memory_service=svc)) as c:
        response = c.get("/stats")

    data = response.json()
    assert data["total"] == 3
    assert data["by_type"]["decision"] == 1
    assert data["by_type"]["convention"] == 2
    assert "episode" not in data["by_type"]


@pytest.mark.unit
def test_stats_growth_counts_recent_memories() -> None:
    """Newly retained memories appear in all growth windows."""
    svc = _make_service()
    svc.retain("recent memory", MemoryType.EPISODE)

    with TestClient(create_app(memory_service=svc)) as c:
        data = c.get("/stats").json()

    assert data["growth"]["last_24h"] == 1
    assert data["growth"]["last_7d"] == 1
    assert data["growth"]["last_30d"] == 1


@pytest.mark.unit
def test_stats_last_recall_ms_populated_after_recall() -> None:
    """last_recall_ms is None before any recall and a positive float after."""
    svc = _make_service()
    svc.retain("timing test memory", MemoryType.DECISION)

    with TestClient(create_app(memory_service=svc)) as c:
        assert c.get("/stats").json()["last_recall_ms"] is None
        svc.recall("timing test")
        data = c.get("/stats").json()

    assert data["last_recall_ms"] is not None
    assert data["last_recall_ms"] > 0


# ---------------------------------------------------------------------------
# /collections
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_collections_returns_list_with_sizes(client: TestClient) -> None:
    response = client.get("/collections")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 1
    entry = data[0]
    assert "name" in entry
    assert "count" in entry
    assert isinstance(entry["count"], int)


@pytest.mark.unit
def test_collections_count_reflects_retained_memories() -> None:
    svc = _make_service()
    svc.retain("memory one", MemoryType.DECISION)
    svc.retain("memory two", MemoryType.CONVENTION)

    with TestClient(create_app(memory_service=svc)) as c:
        data = c.get("/collections").json()

    # The project's collection should report 2 records
    counts = {entry["name"]: entry["count"] for entry in data}
    assert any(v == 2 for v in counts.values())

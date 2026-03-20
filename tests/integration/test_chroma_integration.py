"""Integration tests for ChromaVectorStore — persistence across client restarts."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import chromadb
import pytest

if TYPE_CHECKING:
    from pathlib import Path

from memkernel.config import MemKernelSettings
from memkernel.storage.chroma import ChromaVectorStore


def _unit_embedding(text: str, dim: int = 8) -> list[float]:
    raw = [b / 255.0 for b in hashlib.sha256(text.encode()).digest()[:dim]]
    norm = sum(x * x for x in raw) ** 0.5
    return [x / norm if norm > 0 else 0.0 for x in raw]


def _make_settings(project_id: str = "integ-project") -> MemKernelSettings:
    return MemKernelSettings(project_id=project_id)


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

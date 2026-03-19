"""Shared test fixtures and configuration."""

from __future__ import annotations

import hashlib

import pytest


class MockEmbedding:
    """Deterministic fake embeddings based on content hash."""

    def __init__(self, dimension: int = 8) -> None:
        self._dimension = dimension

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._hash_embed(t) for t in texts]

    def _hash_embed(self, text: str) -> list[float]:
        h = hashlib.sha256(text.encode()).digest()
        raw = [b / 255.0 for b in h[: self._dimension]]
        norm = sum(x * x for x in raw) ** 0.5
        return [x / norm if norm > 0 else 0.0 for x in raw]

    @property
    def dimension(self) -> int:
        return self._dimension


@pytest.fixture
def mock_embedding() -> MockEmbedding:
    return MockEmbedding()

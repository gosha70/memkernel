"""Unit tests for the embedding adapter (MockEmbedding only — fast, hermetic)."""

from __future__ import annotations

import pytest

from tests.conftest import MockEmbedding


@pytest.mark.unit
def test_mock_embed_single_text_returns_one_vector(mock_embedding: MockEmbedding) -> None:
    result = mock_embedding.embed(["hello world"])
    assert len(result) == 1
    assert len(result[0]) == mock_embedding.dimension


@pytest.mark.unit
def test_mock_embed_batch_returns_correct_count(mock_embedding: MockEmbedding) -> None:
    result = mock_embedding.embed(["foo", "bar"])
    assert len(result) == 2
    assert all(len(v) == mock_embedding.dimension for v in result)


@pytest.mark.unit
def test_mock_dimension_property(mock_embedding: MockEmbedding) -> None:
    assert mock_embedding.dimension == 8


@pytest.mark.unit
def test_mock_custom_dimension() -> None:
    emb = MockEmbedding(dimension=16)
    assert emb.dimension == 16
    result = emb.embed(["test"])
    assert len(result[0]) == 16


@pytest.mark.unit
def test_mock_embed_is_deterministic(mock_embedding: MockEmbedding) -> None:
    text = "some deterministic text"
    v1 = mock_embedding.embed([text])[0]
    v2 = mock_embedding.embed([text])[0]
    assert v1 == v2


@pytest.mark.unit
def test_mock_different_texts_differ(mock_embedding: MockEmbedding) -> None:
    v1 = mock_embedding.embed(["text one"])[0]
    v2 = mock_embedding.embed(["text two"])[0]
    assert v1 != v2


@pytest.mark.unit
def test_mock_embedding_is_unit_vector(mock_embedding: MockEmbedding) -> None:
    vec = mock_embedding.embed(["normalised"])[0]
    norm = sum(x * x for x in vec) ** 0.5
    assert abs(norm - 1.0) < 1e-6

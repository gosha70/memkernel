"""Integration tests for SentenceTransformerEmbedding (requires model cache/network)."""

from __future__ import annotations

import pytest


@pytest.mark.integration
@pytest.mark.slow
def test_st_embed_single_text_returns_correct_shape() -> None:
    from memkernel.config import MemKernelSettings
    from memkernel.retrieval.embeddings import SentenceTransformerEmbedding

    settings = MemKernelSettings()
    emb = SentenceTransformerEmbedding(settings)
    result = emb.embed(["hello world"])
    assert len(result) == 1
    assert len(result[0]) == emb.dimension


@pytest.mark.integration
@pytest.mark.slow
def test_st_embed_batch_returns_two_embeddings() -> None:
    from memkernel.config import MemKernelSettings
    from memkernel.retrieval.embeddings import SentenceTransformerEmbedding

    settings = MemKernelSettings()
    emb = SentenceTransformerEmbedding(settings)
    result = emb.embed(["foo", "bar"])
    assert len(result) == 2
    assert all(len(v) == emb.dimension for v in result)


@pytest.mark.integration
@pytest.mark.slow
def test_st_dimension_property() -> None:
    from memkernel.config import MemKernelSettings
    from memkernel.retrieval.embeddings import SentenceTransformerEmbedding

    settings = MemKernelSettings()
    emb = SentenceTransformerEmbedding(settings)
    assert emb.dimension > 0


@pytest.mark.integration
@pytest.mark.slow
def test_st_embed_is_deterministic() -> None:
    from memkernel.config import MemKernelSettings
    from memkernel.retrieval.embeddings import SentenceTransformerEmbedding

    settings = MemKernelSettings()
    emb = SentenceTransformerEmbedding(settings)
    text = "deterministic embedding check"
    v1 = emb.embed([text])[0]
    v2 = emb.embed([text])[0]
    assert v1 == v2

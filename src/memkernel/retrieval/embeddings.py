"""Embedding adapter for MemKernel — sentence-transformers backend."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from memkernel.config import MemKernelSettings


class SentenceTransformerEmbedding:
    """EmbeddingPort implementation backed by sentence-transformers."""

    def __init__(self, settings: MemKernelSettings) -> None:
        # Lazy import: sentence_transformers is heavy; defer until first use.
        from sentence_transformers import SentenceTransformer

        self._model = SentenceTransformer(settings.embedding_model)
        raw_dim = self._model.get_sentence_embedding_dimension()
        if raw_dim is None:
            raise ValueError(
                f"Model '{settings.embedding_model}' returned None for embedding dimension. "
                "Ensure the model has a known output dimension."
            )
        self._dimension: int = raw_dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one embedding vector per input text."""
        import numpy as np

        raw = self._model.encode(texts, convert_to_numpy=True)
        return [row.tolist() for row in np.atleast_2d(raw)]

    @property
    def dimension(self) -> int:
        """Dimensionality of the embedding vectors."""
        return self._dimension

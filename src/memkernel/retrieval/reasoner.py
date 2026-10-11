# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""Built-in, LLM-free reasoner implementing ReasonerPort (ADR-009 fallback).

``LocalReasoner`` never calls a model: it splits the content into token chunks,
ranks them against the question with the same components recall uses
(dense cosine + BM25, fused by RRF) and returns the best chunks as the
answer under ``mode="rag"``. An external reasoner (RLM Studio) replaces it
through ``MEMKERNEL_REASONER``.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from memkernel.core.models import Answer, ReasonerError, SearchResult
from memkernel.retrieval.chunking import split_text
from memkernel.retrieval.search import rrf_fuse
from memkernel.retrieval.sparse import BM25Index

if TYPE_CHECKING:
    from memkernel.config import MemKernelSettings
    from memkernel.core.ports import EmbeddingPort

RAG_MODE = "rag"
_CHUNK_JOINER = "\n\n"


class ReasonerUnavailable(ReasonerError):  # noqa: N818 — name fixed by spec FR-007
    """Raised by a reasoner adapter whose backing package cannot be imported."""


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm > 0 else 0.0


class LocalReasoner:
    """``ReasonerPort`` over hybrid search: returns the chunks that best match the question."""

    def __init__(self, embedding: EmbeddingPort, settings: MemKernelSettings) -> None:
        self._embedding = embedding
        self._settings = settings

    def ask(self, content: str, question: str, mode: str) -> Answer:
        """Rank the content's chunks against ``question``; ``mode`` is accepted but always answered as rag."""
        chunks = split_text(content, self._settings.chunk_size, self._settings.chunk_overlap)
        if not chunks:
            return Answer(answer="", mode=RAG_MODE, citations=[], usage={"chunks": 0, "returned": 0, "tokens": 0})

        dense = self._dense_rank(chunks, question)
        sparse = self._sparse_rank(chunks, question)
        # Exact-term (BM25) hits win ties over dense neighbours: a question
        # usually names the identifier or phrase it is about.
        fused = rrf_fuse(self._settings.rrf_k, sparse, dense)
        top = fused[: max(1, self._settings.ask_top_k)]
        selected = [(int(ref_id), chunks[int(ref_id)]) for ref_id, _ in top]
        answer = _CHUNK_JOINER.join(text for _, text in selected)
        citations = [f"[chunk {index + 1}/{len(chunks)}] {text}" for index, text in selected]
        usage: dict[str, float | int] = {
            "chunks": len(chunks),
            "returned": len(selected),
            "tokens": max(1, len(answer) // 4),
        }
        return Answer(answer=answer, mode=RAG_MODE, citations=citations, usage=usage)

    def _dense_rank(self, chunks: list[str], question: str) -> list[SearchResult]:
        vectors = self._embedding.embed([question, *chunks])
        query, chunk_vectors = vectors[0], vectors[1:]
        scored = sorted(
            ((i, _cosine(query, vector)) for i, vector in enumerate(chunk_vectors)),
            key=lambda item: item[1],
            reverse=True,
        )
        return [SearchResult(ref_id=str(i), score=score, rank=rank) for rank, (i, score) in enumerate(scored, start=1)]

    @staticmethod
    def _sparse_rank(chunks: list[str], question: str) -> list[SearchResult]:
        index = BM25Index()
        index.rebuild([(str(i), chunk) for i, chunk in enumerate(chunks)])
        return index.search_all(question)

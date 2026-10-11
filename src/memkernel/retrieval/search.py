# Copyright (c) EGOGE - All Rights Reserved.
# This software may be used and distributed according to the terms of the MIT license.
"""Hybrid search engine: dense (ChromaDB) + sparse (BM25) fused via RRF."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from memkernel.core.models import ArtifactRef, Memory, SearchResult
from memkernel.memory.lifecycle import recency_score

if TYPE_CHECKING:
    from memkernel.config import MemKernelSettings
    from memkernel.core.models import SearchQuery
    from memkernel.core.ports import EmbeddingPort, SparseIndexPort, VectorStorePort


# Map ChromaDB metadata field names to Memory attribute names.
_FIELD_MAP: dict[str, str] = {
    "type": "type",
    "tier": "tier",
    "session_id": "session_id",
    "checkpoint": "checkpoint",
    "project_id": "project_id",
}


class HybridSearchService:
    """Fuses dense and sparse search results via Reciprocal Rank Fusion (RRF).

    Dense search: ChromaDB cosine-similarity query via VectorStorePort.
    Sparse search: BM25Plus over the full corpus via SparseIndexPort, then
                   post-filtered against the ChromaDB metadata via get_by_id.
    Fusion: RRF with configurable k (default 60).
    Scoring: the fused relevance rank is re-weighted by recency (per-tier
             exponential decay) and importance, following the
             relevance + recency + importance retrieval function of
             Generative Agents (Park et al., 2023). Weights come from settings.
    """

    def __init__(
        self,
        vector_store: VectorStorePort,
        embedding: EmbeddingPort,
        sparse_index: SparseIndexPort,
        settings: MemKernelSettings,
    ) -> None:
        self._vector_store = vector_store
        self._embedding = embedding
        self._sparse_index = sparse_index
        self._settings = settings

    def search(self, query: SearchQuery) -> list[ArtifactRef]:
        """Run hybrid search and return up to query.top_k ArtifactRefs."""
        where = _build_where_filter(query)
        over_fetch = max(1, query.top_k * 3)

        # Dense pass
        query_embedding = self._embedding.embed([query.query_text])[0]
        dense_results = self._vector_store.search_dense(query_embedding, over_fetch, where)

        # Sparse pass — score all, then post-filter to honour metadata filters
        sparse_all = self._sparse_index.search_all(query.query_text)
        sparse_results = filter_sparse_results(sparse_all, where, self._vector_store)
        sparse_results = sparse_results[:over_fetch]

        # RRF fusion
        fused = rrf_fuse(self._settings.rrf_k, dense_results, sparse_results)

        # Hydrate every fused candidate (not just top_k): re-weighting can
        # promote a lower-ranked but recent/important memory into the top_k.
        refs = build_artifact_refs(fused, len(fused), self._vector_store, self._settings.preview_length)
        refs = rescore(refs, self._settings, self._vector_store)
        return refs[: query.top_k]


# ------------------------------------------------------------------
# Module-level helpers (pure functions, easier to unit-test independently)
# ------------------------------------------------------------------


def _build_where_filter(query: SearchQuery) -> dict[str, Any] | None:
    """Construct a ChromaDB ``where`` filter dict from a SearchQuery.

    Returns None when no filters are active (avoids passing an empty dict
    to ChromaDB which would cause a validation error).
    """
    conditions: list[dict[str, Any]] = []
    if query.type_filter is not None:
        conditions.append({"type": query.type_filter.value})
    if query.tier_filter is not None:
        conditions.append({"tier": query.tier_filter.value})
    if query.session_id_filter is not None:
        conditions.append({"session_id": query.session_id_filter})
    if query.checkpoint_only:
        conditions.append({"checkpoint": True})

    if not conditions:
        return None
    if len(conditions) == 1:
        return conditions[0]
    return {"$and": conditions}


def rrf_fuse(
    k: int,
    *result_lists: list[SearchResult],
) -> list[tuple[str, float]]:
    """Reciprocal Rank Fusion across arbitrarily many ranked lists.

    score(d) = sum of  1 / (k + rank_i(d))  for each list that contains d.

    Returns (ref_id, fused_score) pairs sorted descending by score.
    """
    scores: dict[str, float] = {}
    for results in result_lists:
        for result in results:
            rrf_score = 1.0 / (k + result.rank)
            scores[result.ref_id] = scores.get(result.ref_id, 0.0) + rrf_score
    return sorted(scores.items(), key=lambda x: x[1], reverse=True)


def rescore(
    refs: list[ArtifactRef],
    settings: MemKernelSettings,
    vector_store: VectorStorePort,
) -> list[ArtifactRef]:
    """Re-rank fused results by relevance + recency + importance.

    The fused RRF score is min-max normalised to [0, 1] so the three axes
    are commensurable; then::

        final = w_rel * relevance + w_rec * recency + w_imp * importance

    Recency uses the per-tier half-life from settings (long-term memories do
    not decay). The ``last_accessed`` timestamp is consulted so that a memory
    the agent keeps recalling stays fresh (rehearsal).
    """
    if not refs:
        return refs
    scores = [r.score for r in refs]
    lo, hi = min(scores), max(scores)
    span = hi - lo
    rescored: list[ArtifactRef] = []
    for ref in refs:
        relevance = (ref.score - lo) / span if span > 0 else 1.0
        memory = vector_store.get_by_id(ref.ref_id)
        last_accessed = memory.last_accessed if memory is not None else None
        recency = recency_score(ref.type, ref.timestamp, settings, last_accessed=last_accessed)
        final = (
            settings.recall_weight_relevance * relevance
            + settings.recall_weight_recency * recency
            + settings.recall_weight_importance * ref.importance
        )
        rescored.append(ref.model_copy(update={"score": final}))
    rescored.sort(key=lambda r: r.score, reverse=True)
    return rescored


def _metadata_matches(memory: Memory, where: dict[str, Any]) -> bool:
    """Check whether a Memory satisfies a ChromaDB-style where filter.

    Supports the subset of ChromaDB filter syntax used by this module:
      - Simple equality: {"field": value}
      - $and: [cond, ...]
    """
    if "$and" in where:
        return all(_metadata_matches(memory, cond) for cond in where["$and"])

    for key, value in where.items():
        actual = getattr(memory, _FIELD_MAP.get(key, key), None)
        if actual is None:
            return False
        # MemoryType is a StrEnum — compare via string value
        if hasattr(actual, "value"):
            actual = actual.value
        if actual != value:
            return False
    return True


def filter_sparse_results(
    results: list[SearchResult],
    where: dict[str, Any] | None,
    vector_store: VectorStorePort,
) -> list[SearchResult]:
    """Post-filter BM25 results against ChromaDB metadata.

    For each BM25 result, fetch the Memory from the vector store.
    Stale entries (get_by_id returns None) are skipped silently.
    Surviving results are re-ranked 1-based.
    """
    kept: list[SearchResult] = []
    for result in results:
        memory = vector_store.get_by_id(result.ref_id)
        if memory is None:
            continue
        if where is not None and not _metadata_matches(memory, where):
            continue
        kept.append(result)

    return [SearchResult(ref_id=r.ref_id, score=r.score, rank=new_rank) for new_rank, r in enumerate(kept, start=1)]


def build_artifact_refs(
    fused: list[tuple[str, float]],
    top_k: int,
    vector_store: VectorStorePort,
    preview_length: int,
) -> list[ArtifactRef]:
    """Fetch full Memory for each fused result and build ArtifactRef list.

    Stale entries (get_by_id returns None) are skipped silently.
    Stops after collecting top_k valid results.
    """
    refs: list[ArtifactRef] = []
    for ref_id, score in fused:
        if len(refs) >= top_k:
            break
        memory = vector_store.get_by_id(ref_id)
        if memory is None:
            continue
        refs.append(
            ArtifactRef(
                ref_id=memory.ref_id,
                preview=memory.content[:preview_length],
                score=score,
                token_count=memory.token_count,
                type=memory.type,
                timestamp=memory.timestamp,
                tier=memory.tier,
                importance=memory.importance,
            )
        )
    return refs

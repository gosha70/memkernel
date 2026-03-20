"""MemoryService — primary domain service for retain/recall/get/forget."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

from memkernel.core.models import ArtifactRef, Memory, MemoryType, SearchQuery
from memkernel.memory.dedup import compute_content_hash
from memkernel.memory.lifecycle import is_expired

if TYPE_CHECKING:
    from memkernel.config import MemKernelSettings
    from memkernel.core.ports import EmbeddingPort, SparseIndexPort, VectorStorePort
    from memkernel.retrieval.search import HybridSearchService

logger = logging.getLogger(__name__)


class MemoryService:
    """Orchestrates retain, recall, get, and forget operations.

    This is the only entry point for domain logic — MCP tools and the admin
    API both delegate to this service.

    Deduplication (ADR-5): identical content + same type within a project
    returns the existing ref_id and bumps session_id / timestamp.
    Same content + different type is treated as a separate memory.
    """

    def __init__(
        self,
        vector_store: VectorStorePort,
        embedding: EmbeddingPort,
        sparse_index: SparseIndexPort,
        search_service: HybridSearchService,
        settings: MemKernelSettings,
    ) -> None:
        self._vector_store = vector_store
        self._embedding = embedding
        self._sparse_index = sparse_index
        self._search_service = search_service
        self._settings = settings

    # ------------------------------------------------------------------
    # Core operations
    # ------------------------------------------------------------------

    def retain(
        self,
        content: str,
        type: MemoryType,  # noqa: A002  (shadows built-in intentionally)
        session_id: str | None = None,
        checkpoint: bool = False,
        source: str = "",
    ) -> str:
        """Store content and return its ref_id.

        Idempotent for identical content + type within a project: returns the
        existing ref_id and updates session_id / timestamp / checkpoint.
        """
        resolved_session = session_id or self._settings.default_session_id
        content_hash = compute_content_hash(content)

        # Dedup check: same hash + same type -> update metadata, return existing id
        existing = self._vector_store.find_by_hash(content_hash, type.value)
        if existing is not None:
            now = datetime.now(UTC)
            self._vector_store.update_metadata(
                existing.ref_id,
                {
                    "session_id": resolved_session,
                    "timestamp": now.isoformat(),
                    "checkpoint": checkpoint,
                },
            )
            return existing.ref_id

        # New memory
        ref_id = str(uuid4())
        now = datetime.now(UTC)
        token_count = max(1, len(content) // 4)
        embedding = self._embedding.embed([content])[0]
        metadata = {
            "project_id": self._settings.project_id,
            "session_id": resolved_session,
            "timestamp": now.isoformat(),
            "type": type.value,
            "source": source,
            "hash": content_hash,
            "token_count": token_count,
            "checkpoint": checkpoint,
        }

        # Authoritative store first
        self._vector_store.upsert(
            ref_id=ref_id,
            content=content,
            embedding=embedding,
            metadata=metadata,
        )

        # BM25 is a derived index — failure is non-fatal
        try:
            self._sparse_index.add(ref_id, content)
        except Exception:
            logger.warning("BM25 add failed for %s", ref_id)
            self._sparse_index.mark_needs_rebuild()

        return ref_id

    def recall(
        self,
        query: str,
        type: MemoryType | None = None,  # noqa: A002
        session_id: str | None = None,
        checkpoint_only: bool = False,
        top_k: int | None = None,
    ) -> list[ArtifactRef]:
        """Search for memories matching the query.

        Returns a list of ArtifactRef (lightweight references, no full content).
        Expired memories are filtered out from the results.
        BM25 index is self-healed (rebuilt from vector store) if needs_rebuild is set.
        """
        if self._sparse_index.needs_rebuild:
            self.rebuild_sparse_index()

        desired_k = top_k if top_k is not None else self._settings.search_top_k

        # Iteratively widen the fetch window until we have enough live results
        # or the store is fully exhausted. No fixed ceiling: the store_exhausted
        # guard is the correct termination condition and handles any corpus size.
        fetch_k = desired_k * 2
        live: list[ArtifactRef] = []

        while True:
            search_query = SearchQuery(
                query_text=query,
                type_filter=type,
                session_id_filter=session_id,
                checkpoint_only=checkpoint_only,
                top_k=fetch_k,
            )
            results = self._search_service.search(search_query)
            live = [r for r in results if not is_expired(r.type, r.timestamp, self._settings)]

            store_exhausted = len(results) < fetch_k
            if len(live) >= desired_k or store_exhausted:
                break

            fetch_k *= 2

        return live[:desired_k]

    def count(self) -> int:
        """Return the total number of memories stored in this project."""
        return self._vector_store.count()

    def get(self, ref_id: str) -> Memory | None:
        """Fetch full memory content by ref_id. Returns None if not found."""
        return self._vector_store.get_by_id(ref_id)

    def forget(self, ref_id: str) -> bool:
        """Delete a memory from all stores.

        Returns True if the memory existed and was deleted, False otherwise.
        BM25 removal failure is non-fatal — the index is marked for rebuild.
        """
        deleted = self._vector_store.delete(ref_id)
        try:
            self._sparse_index.remove(ref_id)
        except Exception:
            logger.warning("BM25 remove failed for %s", ref_id)
            self._sparse_index.mark_needs_rebuild()
        return deleted

    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------

    def rebuild_sparse_index(self) -> None:
        """Rebuild the BM25 index from scratch using the vector store as source of truth."""
        all_memories = self._vector_store.list_all()
        documents = [(m.ref_id, m.content) for m in all_memories]
        self._sparse_index.rebuild(documents)

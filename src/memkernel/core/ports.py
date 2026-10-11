# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""Protocol definitions for MemKernel adapters.

Domain logic in core/ depends ONLY on these protocols.
Concrete implementations live in storage/, retrieval/, etc.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from memkernel.core.models import Memory, SearchResult


@runtime_checkable
class VectorStorePort(Protocol):
    """Dense vector store backend (ChromaDB for MVP)."""

    def upsert(
        self,
        ref_id: str,
        content: str,
        embedding: list[float],
        metadata: dict[str, Any],
    ) -> None: ...

    def search_dense(
        self,
        query_embedding: list[float],
        top_k: int,
        where: dict[str, Any] | None = None,
    ) -> list[SearchResult]: ...

    def get_by_id(self, ref_id: str) -> Memory | None: ...

    def delete(self, ref_id: str) -> bool: ...

    def list_all(self, where: dict[str, Any] | None = None) -> list[Memory]: ...

    def find_by_hash(self, content_hash: str, memory_type: str) -> Memory | None:
        """Find by content_hash + type (dedup key per ADR-5)."""
        ...

    def update_metadata(self, ref_id: str, metadata: dict[str, Any]) -> None:
        """Fetch-and-merge: only overwrites caller-specified keys."""
        ...

    def count(self) -> int: ...

    def list_collections(self) -> list[dict[str, Any]]:
        """List all collections visible to this adapter with their record counts."""
        ...


@runtime_checkable
class EmbeddingPort(Protocol):
    """Text embedding model."""

    def embed(self, texts: list[str]) -> list[list[float]]: ...

    @property
    def dimension(self) -> int: ...


@runtime_checkable
class SparseIndexPort(Protocol):
    """BM25 sparse search index."""

    def add(self, ref_id: str, content: str) -> None: ...

    def remove(self, ref_id: str) -> None: ...

    def search(self, query: str, top_k: int) -> list[SearchResult]: ...

    def search_all(self, query: str) -> list[SearchResult]:
        """Score entire corpus, return all results with score > 0."""
        ...

    def rebuild(self, documents: list[tuple[str, str]]) -> None: ...

    @property
    def needs_rebuild(self) -> bool: ...

    def mark_needs_rebuild(self) -> None: ...

    def __len__(self) -> int: ...


@runtime_checkable
class ChunkerPort(Protocol):
    """Code/text chunking strategy (stub for future US3)."""

    def chunk(self, content: str, metadata: dict[str, Any]) -> list[str]: ...

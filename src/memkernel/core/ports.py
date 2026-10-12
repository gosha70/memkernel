# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""Protocol definitions for MemKernel adapters.

Domain logic in core/ depends ONLY on these protocols.
Concrete implementations live in storage/, retrieval/, etc.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from memkernel.core.models import Answer, Memory, SearchResult


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

    def count(self, where: dict[str, Any] | None = None) -> int:
        """Number of records, optionally only those matching a metadata filter (ids-only fetch)."""
        ...

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


@runtime_checkable
class DocumentStorePort(Protocol):
    """Document bodies: stored whole, chunk-indexed, searchable per document (ADR-009)."""

    def put(self, content: str, name: str) -> str:
        """Store a document body and return its doc_id (idempotent for identical content)."""
        ...

    def get(self, doc_id: str) -> str | None:
        """Return the stored body, or None if ``doc_id`` is unknown."""
        ...

    def index(self, doc_id: str, chunks: list[str]) -> int:
        """Index the chunks of a stored document; returns the number of chunks indexed."""
        ...

    def indexed(self, doc_id: str) -> int:
        """Number of chunks currently indexed for ``doc_id`` (0 for an unknown or un-indexed body); ids-only."""
        ...

    def search(self, doc_id: str, query: str, top_k: int) -> list[str]:
        """Return the top_k chunk texts of one document ranked against ``query``."""
        ...


@runtime_checkable
class ReasonerPort(Protocol):
    """Answers a question about a body of text in a given mode (direct | rag | rlm | auto)."""

    def ask(self, content: str, question: str, mode: str) -> Answer: ...

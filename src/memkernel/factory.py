# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""Public factory for a fully wired :class:`MemoryService`.

Embedders of MemKernel (Claude Code hooks, the ``haa`` harness, scripts) should
build the service through :func:`build_service` instead of assembling the
adapters by hand, so that internal refactors do not break them. This is the
supported Python entry point; the MCP server and the admin API use it too.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from memkernel.config import MemKernelSettings
from memkernel.core.services import MemoryService
from memkernel.retrieval.search import HybridSearchService
from memkernel.retrieval.sparse import BM25Index
from memkernel.storage.chroma import ChromaVectorStore

if TYPE_CHECKING:
    from chromadb.api import ClientAPI

    from memkernel.core.ports import ChunkerPort, EmbeddingPort


def build_service(
    settings: MemKernelSettings | None = None,
    embedding: EmbeddingPort | None = None,
    chunker: ChunkerPort | None = None,
    chroma_client: ClientAPI | None = None,
    rebuild_sparse_index: bool = True,
) -> MemoryService:
    """Return a ready-to-use MemoryService wired to ChromaDB + BM25 + sentence-transformers.

    ``settings`` defaults to environment-driven :class:`MemKernelSettings`.
    ``embedding`` defaults to the configured sentence-transformers model (loaded
    lazily here so tests and lightweight callers can pass a mock instead).
    ``chunker`` defaults to the tree-sitter :class:`ASTChunker`.
    """
    resolved = settings or MemKernelSettings()

    if embedding is None:
        from memkernel.retrieval.embeddings import SentenceTransformerEmbedding

        embedding = SentenceTransformerEmbedding(resolved)

    if chunker is None:
        from memkernel.retrieval.chunking import ASTChunker

        chunker = ASTChunker(resolved)

    vector_store = ChromaVectorStore(resolved, client=chroma_client)
    sparse_index = BM25Index()
    search_service = HybridSearchService(
        vector_store=vector_store,
        embedding=embedding,
        sparse_index=sparse_index,
        settings=resolved,
    )
    service = MemoryService(
        vector_store=vector_store,
        embedding=embedding,
        sparse_index=sparse_index,
        search_service=search_service,
        settings=resolved,
        chunker=chunker,
    )
    if rebuild_sparse_index:
        service.rebuild_sparse_index()
    return service

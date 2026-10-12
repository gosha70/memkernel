# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""Public factory for a fully wired :class:`MemoryService`.

Embedders of MemKernel (Claude Code hooks, the ``haa`` harness, scripts) should
build the service through :func:`build_service` instead of assembling the
adapters by hand, so that internal refactors do not break them. This is the
supported Python entry point; the MCP server and the admin API use it too.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from memkernel.config import MemKernelSettings
from memkernel.core.services import MemoryService
from memkernel.retrieval.chunking import TokenChunker
from memkernel.retrieval.reasoner import LocalReasoner, ReasonerUnavailable
from memkernel.retrieval.search import HybridSearchService
from memkernel.retrieval.sparse import BM25Index
from memkernel.storage.chroma import ChromaVectorStore
from memkernel.storage.documents import LocalDocumentStore

if TYPE_CHECKING:
    from chromadb.api import ClientAPI

    from memkernel.core.ports import ChunkerPort, EmbeddingPort, ReasonerPort

logger = logging.getLogger(__name__)


def build_service(
    settings: MemKernelSettings | None = None,
    embedding: EmbeddingPort | None = None,
    chunker: ChunkerPort | None = None,
    chroma_client: ClientAPI | None = None,
    rebuild_sparse_index: bool = True,
    reasoner: ReasonerPort | None = None,
) -> MemoryService:
    """Return a ready-to-use MemoryService wired to ChromaDB + BM25 + sentence-transformers.

    ``settings`` defaults to environment-driven :class:`MemKernelSettings`.
    ``embedding`` defaults to the configured sentence-transformers model (loaded
    lazily here so tests and lightweight callers can pass a mock instead).
    ``chunker`` defaults to the tree-sitter :class:`ASTChunker`.
    ``reasoner`` defaults to the one ``settings.reasoner`` names; the built-in
    :class:`LocalReasoner` is the LLM-free fallback, both when the configured
    one cannot be built and, at ask() time, when it fails. Documents are stored
    in the built-in :class:`LocalDocumentStore` (``settings.document_store``).
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
    document_store = LocalDocumentStore(vector_store, embedding, sparse_index, resolved)
    resolved_reasoner = reasoner if reasoner is not None else _build_reasoner(resolved, embedding)
    external = not isinstance(resolved_reasoner, LocalReasoner)
    service = MemoryService(
        vector_store=vector_store,
        embedding=embedding,
        sparse_index=sparse_index,
        search_service=search_service,
        settings=resolved,
        chunker=chunker,
        document_store=document_store,
        document_chunker=TokenChunker(resolved),
        reasoner=resolved_reasoner,
        # An external reasoner that fails at ask() time degrades to the local one.
        fallback_reasoner=LocalReasoner(embedding, resolved) if external else None,
        local_reasoner=not external,
        # The local reasoner only retrieves; it cannot distil statements, so
        # consolidate(synthesize=True) gets a synthesizer only when an external
        # (LLM-backed) reasoner is in place.
        synthesizer=resolved_reasoner if external else None,
    )
    if rebuild_sparse_index:
        service.rebuild_sparse_index()
    return service


def _build_reasoner(settings: MemKernelSettings, embedding: EmbeddingPort) -> ReasonerPort:
    """Return the ReasonerPort named by ``settings.reasoner``, falling back to the local one."""
    if settings.reasoner == "rlmstudio":
        from memkernel.adapters.rlmstudio import RLMStudioReasoner

        try:
            return RLMStudioReasoner()
        except ReasonerUnavailable as exc:
            logger.warning("MEMKERNEL_REASONER=rlmstudio but %s; falling back to the local reasoner", exc)
    return LocalReasoner(embedding, settings)

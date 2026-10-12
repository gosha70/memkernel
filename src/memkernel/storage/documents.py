# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""Built-in document store implementing DocumentStorePort on the memkernel collection.

A document is kept as three kinds of records in the same ChromaDB collection
(ADR-009, plan ADR-2):

* the **body**: one canonical record whose id is content-addressed
  (``doc-<sha256>``), tagged ``document_body`` — never returned by recall;
* the **chunks**: one record per token chunk, tagged ``document_chunk`` with
  ``chunk_index`` and ``document_id`` metadata, indexed in both the dense and
  the BM25 index so a phrase deep inside the document is findable;
* the **summary**: the memkernel ``document`` memory itself, written by
  :class:`~memkernel.core.services.MemoryService`, not by this store.

No extra dependency: ``document`` works wherever memkernel works.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from memkernel.core.models import (
    DEFAULT_IMPORTANCE,
    DOCUMENT_BODY_TAG,
    DOCUMENT_CHUNK_TAG,
    DOCUMENT_PART_KEY,
    MemoryType,
    SearchResult,
    tier_of,
)
from memkernel.memory.dedup import compute_content_hash
from memkernel.retrieval.search import rrf_fuse

if TYPE_CHECKING:
    from memkernel.config import MemKernelSettings
    from memkernel.core.ports import EmbeddingPort, SparseIndexPort, VectorStorePort

logger = logging.getLogger(__name__)

_DOC_ID_PREFIX = "doc-"
_CHUNK_ID_SEPARATOR = "-chunk-"


def _rerank(results: list[SearchResult]) -> list[SearchResult]:
    """Re-number ranks 1..n after filtering a ranked list down to one document's chunks."""
    return [SearchResult(ref_id=r.ref_id, score=r.score, rank=rank) for rank, r in enumerate(results, start=1)]


class LocalDocumentStore:
    """``DocumentStorePort`` backed by the project's own vector store and BM25 index."""

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

    # ------------------------------------------------------------------
    # DocumentStorePort
    # ------------------------------------------------------------------

    def put(self, content: str, name: str) -> str:
        """Store the body under a content-addressed id; a second put of the same body is a no-op."""
        doc_id = _DOC_ID_PREFIX + compute_content_hash(content)
        if self._vector_store.get_by_id(doc_id) is not None:
            return doc_id
        # The body is embedded only so the record is a valid collection entry;
        # retrieval goes through the chunks, and recall hides the body.
        embedding = self._embedding.embed([content[: self._settings.chunk_size]])[0]
        self._vector_store.upsert(
            ref_id=doc_id,
            content=content,
            embedding=embedding,
            metadata=self._metadata(content, name, doc_id, DOCUMENT_BODY_TAG),
        )
        return doc_id

    def get(self, doc_id: str) -> str | None:
        """Return the body for ``doc_id`` or None when it is not a stored document."""
        memory = self._vector_store.get_by_id(doc_id)
        if memory is None or DOCUMENT_BODY_TAG not in memory.tags:
            return None
        return memory.content

    def index(self, doc_id: str, chunks: list[str]) -> int:
        """Replace the indexed chunks of ``doc_id`` with ``chunks``; returns how many were indexed."""
        body = self._vector_store.get_by_id(doc_id)
        if body is None or DOCUMENT_BODY_TAG not in body.tags:
            raise ValueError(f"unknown document: {doc_id}")
        for stale in self._chunk_records(doc_id):
            self._vector_store.delete(stale.ref_id)
            self._sparse_remove(stale.ref_id)
        if not chunks:
            return 0
        embeddings = self._embedding.embed(chunks)
        for position, (chunk, embedding) in enumerate(zip(chunks, embeddings, strict=True)):
            ref_id = f"{doc_id}{_CHUNK_ID_SEPARATOR}{position}"
            metadata = self._metadata(chunk, body.source, doc_id, DOCUMENT_CHUNK_TAG)
            metadata["chunk_index"] = position
            self._vector_store.upsert(ref_id=ref_id, content=chunk, embedding=embedding, metadata=metadata)
            try:
                self._sparse_index.add(ref_id, chunk)
            except Exception:
                logger.warning("BM25 add failed for document chunk %s", ref_id)
                self._sparse_index.mark_needs_rebuild()
        return len(chunks)

    def indexed(self, doc_id: str) -> int:
        """Count the chunk records of ``doc_id`` without loading them (chunks are the records with a chunk_index)."""
        return self._vector_store.count(where={"$and": [{"document_id": doc_id}, {"chunk_index": {"$gte": 0}}]})

    def search(self, doc_id: str, query: str, top_k: int) -> list[str]:
        """Hybrid search (dense + BM25, RRF-fused) restricted to one document's chunks; best chunk texts first.

        This is the retrieval step of ``ask`` for the LLM-free reasoner: the
        chunks were embedded and BM25-indexed at ``index`` time, so nothing is
        re-embedded here but the query.
        """
        if top_k <= 0:
            return []
        prefix = f"{doc_id}{_CHUNK_ID_SEPARATOR}"
        query_embedding = self._embedding.embed([query])[0]
        # The where-filter also matches the body and the summary record, which
        # carry the same document_id: over-fetch by two and keep chunk ids only.
        dense = [
            r
            for r in self._vector_store.search_dense(query_embedding, top_k + 2, where={"document_id": doc_id})
            if r.ref_id.startswith(prefix)
        ]
        sparse = [r for r in self._sparse_index.search_all(query) if r.ref_id.startswith(prefix)]
        # Exact-term hits win ties, as in LocalReasoner: a question usually names what it is about.
        fused = rrf_fuse(self._settings.rrf_k, _rerank(sparse), _rerank(dense))
        texts: list[str] = []
        for ref_id, _ in fused:
            if len(texts) >= top_k:
                break
            memory = self._vector_store.get_by_id(ref_id)
            if memory is not None:
                texts.append(memory.content)
        return texts

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _chunk_records(self, doc_id: str) -> list[Any]:
        return [m for m in self._vector_store.list_all({"document_id": doc_id}) if DOCUMENT_CHUNK_TAG in m.tags]

    def _sparse_remove(self, ref_id: str) -> None:
        try:
            self._sparse_index.remove(ref_id)
        except Exception:
            logger.warning("BM25 remove failed for document chunk %s", ref_id)
            self._sparse_index.mark_needs_rebuild()

    def _metadata(self, content: str, name: str, doc_id: str, tag: str) -> dict[str, Any]:
        memory_type = MemoryType.DOCUMENT
        return {
            "project_id": self._settings.project_id,
            "session_id": self._settings.default_session_id,
            "timestamp": datetime.now(UTC).isoformat(),
            "type": memory_type.value,
            "tier": tier_of(memory_type).value,
            "source": name,
            "hash": compute_content_hash(content),
            "token_count": max(1, len(content) // 4),
            "checkpoint": False,
            "importance": DEFAULT_IMPORTANCE[memory_type],
            "access_count": 0,
            "tags": tag,
            "document_id": doc_id,
            # Parts are shared by every owner of the body and carry no owner
            # session: the default session here is a placeholder, and search
            # exempts parts from metadata filters (see retrieval/search.py).
            DOCUMENT_PART_KEY: True,
        }

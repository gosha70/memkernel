# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""MemoryService — primary domain service for retain/recall/get/forget."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from memkernel.core.models import (
    DEFAULT_IMPORTANCE,
    DOCUMENT_BODY_TAG,
    DOCUMENT_CHUNK_TAG,
    ArtifactRef,
    Memory,
    MemoryTier,
    MemoryType,
    SearchQuery,
    tier_of,
)
from memkernel.memory.dedup import compute_content_hash
from memkernel.memory.lifecycle import memory_is_expired

if TYPE_CHECKING:
    from memkernel.config import MemKernelSettings
    from memkernel.core.ports import (
        ChunkerPort,
        DocumentStorePort,
        EmbeddingPort,
        SparseIndexPort,
        VectorStorePort,
    )
    from memkernel.retrieval.search import HybridSearchService

logger = logging.getLogger(__name__)

# Upper bound on the outline line appended to a document summary, so that
# get(document) is at most ``document_summary_chars`` + 200 characters.
_SUMMARY_OUTLINE_MAX_CHARS = 196
_SUMMARY_SEPARATOR = "\n\n"
_DEFAULT_DOCUMENT_NAME = "document"


@dataclass(frozen=True)
class _ExtraMeta:
    """Optional tiered-memory metadata passed through retain()."""

    importance: float | None = None
    tags: list[str] = field(default_factory=list)
    supersedes: str | None = None
    promoted_from: str | None = None
    document_id: str | None = None


def _is_document_part(memory: Memory) -> bool:
    """True for the body / chunk records a document store keeps beside a document summary."""
    return DOCUMENT_BODY_TAG in memory.tags or DOCUMENT_CHUNK_TAG in memory.tags


def _document_summary(content: str, name: str, chunk_count: int, max_chars: int) -> str:
    """First ``max_chars`` of the body plus one bounded line with line count and outline."""
    lines = content.splitlines()
    headings = [ln.strip().lstrip("#").strip() for ln in lines if ln.lstrip().startswith("#")]
    outline = f"[document {name}: {len(lines)} lines, {len(content)} chars, {chunk_count} chunks"
    if headings:
        outline += "; outline: " + ", ".join(h for h in headings if h)
    outline = outline[: _SUMMARY_OUTLINE_MAX_CHARS - 1] + "…" if len(outline) > _SUMMARY_OUTLINE_MAX_CHARS else outline
    return content[:max_chars] + _SUMMARY_SEPARATOR + outline + "]"


def _artifact_ref(memory: Memory, score: float, preview_length: int) -> ArtifactRef:
    return ArtifactRef(
        ref_id=memory.ref_id,
        preview=memory.content[:preview_length],
        score=score,
        token_count=memory.token_count,
        type=memory.type,
        timestamp=memory.timestamp,
        tier=memory.tier,
        importance=memory.importance,
    )


class MemoryService:
    """Orchestrates retain, recall, get, and forget operations.

    This is the only entry point for domain logic — MCP tools and the admin
    API both delegate to this service.

    Deduplication (ADR-5): identical content + same type within a project
    returns the existing ref_id and bumps session_id / timestamp.
    Same content + different type is treated as a separate memory.

    Tiered memory (ADR-7): every memory belongs to a tier derived from its
    type (working / short_term / long_term). ``recall`` and ``get`` record
    access so that useful short-term memories are reinforced instead of
    expiring; ``promote`` moves knowledge into the long-term tier and
    ``consolidate`` lists what is worth promoting and purges what has decayed.
    """

    def __init__(
        self,
        vector_store: VectorStorePort,
        embedding: EmbeddingPort,
        sparse_index: SparseIndexPort,
        search_service: HybridSearchService,
        settings: MemKernelSettings,
        chunker: ChunkerPort | None = None,
        document_store: DocumentStorePort | None = None,
        document_chunker: ChunkerPort | None = None,
    ) -> None:
        self._vector_store = vector_store
        self._embedding = embedding
        self._sparse_index = sparse_index
        self._search_service = search_service
        self._settings = settings
        self._chunker = chunker
        self._document_store = document_store
        self._document_chunker = document_chunker
        self._last_recall_ms: float | None = None

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
        importance: float | None = None,
        tags: list[str] | None = None,
        supersedes: str | None = None,
        promoted_from: str | None = None,
    ) -> str:
        """Store content and return its ref_id.

        For MemoryType.CODE with a chunker injected: stores the original
        content as the canonical record (so get(retain(code)) always returns
        the full file), then also indexes each AST chunk so recall() can
        match at function/class granularity.  For all other types (or when
        no chunker is set): stores content as a single record.

        ``importance`` (0..1) defaults per type (see ``DEFAULT_IMPORTANCE``).
        ``supersedes`` links a newer memory to the one it replaces so that
        recall can hide the stale version (see ``forget``/``consolidate``).

        For MemoryType.DOCUMENT with a document store injected: the body is
        stored through the store, its token chunks are indexed, and the
        memkernel record keeps only a summary (``get`` never returns the
        body; use ``ask``). ``source`` names the document.

        Idempotent: identical content + type returns the existing ref_id.
        """
        extra = _ExtraMeta(importance=importance, tags=tags or [], supersedes=supersedes, promoted_from=promoted_from)
        if type == MemoryType.DOCUMENT and self._document_store is not None:
            return self._retain_document(content, session_id, checkpoint, source, extra)
        if type == MemoryType.CODE and self._chunker is not None:
            chunks = self._chunker.chunk(content, {"source": source})
            if chunks:
                # Canonical record: original file — preserves get(retain(code)) == code
                ref_id = self._retain_single(content, type, session_id, checkpoint, source, extra)
                # Fine-grained index: each chunk stored for recall() granularity
                chunk_extra = _ExtraMeta(importance=importance, tags=tags or [])
                chunk_ref_ids: list[str] = []
                for chunk in chunks:
                    chunk_ref_ids.append(self._retain_single(chunk, type, session_id, checkpoint, source, chunk_extra))
                # Link chunk ref_ids to canonical so forget() can clean them up
                unique_chunk_refs = list(dict.fromkeys(r for r in chunk_ref_ids if r != ref_id))
                if unique_chunk_refs:
                    self._vector_store.update_metadata(ref_id, {"chunk_refs": ",".join(unique_chunk_refs)})
                return ref_id

        return self._retain_single(content, type, session_id, checkpoint, source, extra)

    def _retain_document(
        self,
        content: str,
        session_id: str | None,
        checkpoint: bool,
        source: str,
        extra: _ExtraMeta,
    ) -> str:
        """Store a document body + chunks through the document store; retain its summary."""
        assert self._document_store is not None  # guarded by the caller
        name = source or _DEFAULT_DOCUMENT_NAME
        doc_id = self._document_store.put(content, name)
        chunks = self._document_chunker.chunk(content, {"source": name}) if self._document_chunker else [content]
        indexed = self._document_store.index(doc_id, chunks)
        summary = _document_summary(content, name, indexed, self._settings.document_summary_chars)
        return self._retain_single(
            summary,
            MemoryType.DOCUMENT,
            session_id,
            checkpoint,
            source,
            replace(extra, document_id=doc_id),
        )

    def _retain_single(
        self,
        content: str,
        type: MemoryType,  # noqa: A002
        session_id: str | None,
        checkpoint: bool,
        source: str,
        extra: _ExtraMeta | None = None,
    ) -> str:
        """Store a single content string and return its ref_id."""
        extra = extra or _ExtraMeta()
        resolved_session = session_id or self._settings.default_session_id
        content_hash = compute_content_hash(content)

        # Dedup check: same hash + same type -> update metadata, return existing id
        existing = self._vector_store.find_by_hash(content_hash, type.value)
        if existing is not None:
            now = datetime.now(UTC)
            update: dict[str, Any] = {
                "session_id": resolved_session,
                "timestamp": now.isoformat(),
                "checkpoint": checkpoint,
            }
            if extra.importance is not None:
                update["importance"] = max(existing.importance, extra.importance)
            if extra.tags:
                update["tags"] = ",".join(dict.fromkeys([*existing.tags, *extra.tags]))
            if extra.supersedes:
                update["supersedes"] = extra.supersedes
            self._vector_store.update_metadata(existing.ref_id, update)
            return existing.ref_id

        # New memory
        ref_id = str(uuid4())
        now = datetime.now(UTC)
        token_count = max(1, len(content) // 4)
        embedding = self._embedding.embed([content])[0]
        importance = extra.importance if extra.importance is not None else DEFAULT_IMPORTANCE[type]
        metadata: dict[str, Any] = {
            "project_id": self._settings.project_id,
            "session_id": resolved_session,
            "timestamp": now.isoformat(),
            "type": type.value,
            "tier": tier_of(type).value,
            "source": source,
            "hash": content_hash,
            "token_count": token_count,
            "checkpoint": checkpoint,
            "importance": max(0.0, min(1.0, importance)),
            "access_count": 0,
            "tags": ",".join(extra.tags),
        }
        if extra.supersedes:
            metadata["supersedes"] = extra.supersedes
        if extra.promoted_from:
            metadata["promoted_from"] = extra.promoted_from
        if extra.document_id:
            metadata["document_id"] = extra.document_id

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
        tier: MemoryTier | None = None,
        touch: bool = True,
    ) -> list[ArtifactRef]:
        """Search for memories matching the query.

        Returns a list of ArtifactRef (lightweight references, no full content).
        Expired and superseded memories are filtered out from the results.
        Returned memories are marked as accessed (``touch``), which reinforces
        their retention — unless ``touch=False`` (used by maintenance paths).
        BM25 index is self-healed (rebuilt from vector store) if needs_rebuild is set.
        """
        _start = time.perf_counter()

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
                tier_filter=tier,
                session_id_filter=session_id,
                checkpoint_only=checkpoint_only,
                top_k=fetch_k,
            )
            results = self._search_service.search(search_query)
            live = self._filter_live(results)

            store_exhausted = len(results) < fetch_k
            if len(live) >= desired_k or store_exhausted:
                break

            fetch_k *= 2

        live = live[:desired_k]
        if touch:
            for ref in live:
                self._touch(ref.ref_id)
        self._last_recall_ms = (time.perf_counter() - _start) * 1000
        return live

    def _filter_live(self, results: list[ArtifactRef]) -> list[ArtifactRef]:
        """Drop expired and superseded memories; resolve document chunk hits to their summary.

        A hit on a document body or chunk record is replaced by the document's
        summary record (the ``document`` memory) carrying the hit's score, so a
        phrase deep inside a document surfaces the document exactly once and
        chunk records never appear as top-level results.
        """
        memories: dict[str, Memory] = {}
        for ref in results:
            memory = self._vector_store.get_by_id(ref.ref_id)
            if memory is not None:
                memories[ref.ref_id] = memory
        superseded = {m.supersedes for m in memories.values() if m.supersedes}
        summaries: dict[str, Memory | None] = {}
        live: list[ArtifactRef] = []
        seen: set[str] = set()
        for ref in results:
            memory = memories.get(ref.ref_id)
            if memory is None:
                continue
            if memory.document_id and _is_document_part(memory):
                if memory.document_id not in summaries:
                    summaries[memory.document_id] = self._document_summary_record(memory.document_id)
                summary = summaries[memory.document_id]
                if summary is None:
                    continue
                memory = summary
                ref = _artifact_ref(summary, ref.score, self._settings.preview_length)
            if ref.ref_id in seen or ref.ref_id in superseded:
                continue
            if memory_is_expired(memory, self._settings):
                continue
            seen.add(ref.ref_id)
            live.append(ref)
        return live

    def _document_summary_record(self, document_id: str) -> Memory | None:
        """Return the ``document`` memory (summary record) that owns ``document_id``."""
        for memory in self._vector_store.list_all({"document_id": document_id}):
            if not _is_document_part(memory):
                return memory
        return None

    def _touch(self, ref_id: str) -> None:
        """Record an access: bump access_count and last_accessed (rehearsal)."""
        memory = self._vector_store.get_by_id(ref_id)
        if memory is None:
            return
        self._vector_store.update_metadata(
            ref_id,
            {"access_count": memory.access_count + 1, "last_accessed": datetime.now(UTC).isoformat()},
        )

    def count(self) -> int:
        """Return the total number of memories stored in this project."""
        return self._vector_store.count()

    def list_memories(
        self,
        tier: MemoryTier | None = None,
        type: MemoryType | None = None,  # noqa: A002
        session_id: str | None = None,
    ) -> list[Memory]:
        """Return memories matching the given filters (no ranking, no access tracking).

        ``tier`` is filtered in Python because records written before tiers
        existed carry no ``tier`` metadata; the adapter derives it from the type.
        """
        conditions: list[dict[str, Any]] = []
        if type is not None:
            conditions.append({"type": type.value})
        if session_id is not None:
            conditions.append({"session_id": session_id})
        where: dict[str, Any] | None = None
        if len(conditions) == 1:
            where = conditions[0]
        elif conditions:
            where = {"$and": conditions}
        memories = [m for m in self._vector_store.list_all(where) if not _is_document_part(m)]
        if tier is not None:
            memories = [m for m in memories if m.tier == tier]
        return memories

    @property
    def project_id(self) -> str:
        """Return the project_id for this service instance."""
        return self._settings.project_id

    def stats(self) -> dict[str, object]:
        """Return total count, per-type breakdown, memory growth, and last recall timing."""
        all_memories = self._vector_store.list_all()
        now = datetime.now(UTC)
        by_type: dict[str, int] = {}
        by_tier: dict[str, int] = {}
        for m in all_memories:
            by_type[m.type.value] = by_type.get(m.type.value, 0) + 1
            by_tier[m.tier.value] = by_tier.get(m.tier.value, 0) + 1
        growth = {
            "last_24h": sum(1 for m in all_memories if m.timestamp >= now - timedelta(hours=24)),
            "last_7d": sum(1 for m in all_memories if m.timestamp >= now - timedelta(days=7)),
            "last_30d": sum(1 for m in all_memories if m.timestamp >= now - timedelta(days=30)),
        }
        return {
            "total": len(all_memories),
            "by_type": by_type,
            "by_tier": by_tier,
            "growth": growth,
            "last_recall_ms": self._last_recall_ms,
        }

    def collection_count(self) -> int:
        """Return the number of collections visible to this server's storage backend."""
        return len(self._vector_store.list_collections())

    def list_collections(self) -> list[dict[str, object]]:
        """Return all collections visible to the storage backend with their record counts."""
        return self._vector_store.list_collections()

    def get(self, ref_id: str, touch: bool = True) -> Memory | None:
        """Fetch full memory content by ref_id. Returns None if not found.

        Reading the full content is the strongest signal that a memory is
        useful, so it is recorded as an access unless ``touch=False``.
        """
        memory = self._vector_store.get_by_id(ref_id)
        if memory is not None and touch:
            self._touch(ref_id)
        return memory

    # ------------------------------------------------------------------
    # Consolidation (short-term -> long-term)
    # ------------------------------------------------------------------

    def promote(
        self,
        ref_id: str,
        type: MemoryType,  # noqa: A002
        content: str | None = None,
        importance: float | None = None,
        tags: list[str] | None = None,
        session_id: str | None = None,
    ) -> str | None:
        """Promote a memory into a (normally long-term) type and return the new ref_id.

        The caller — typically the agent, which is the only component with an
        LLM in the loop — supplies the distilled ``content``; when omitted the
        original content is reused verbatim. The source memory is kept (it
        decays on its own schedule) and linked via ``promoted_from`` so that
        provenance survives. Returns None if ``ref_id`` does not exist.
        """
        source = self._vector_store.get_by_id(ref_id)
        if source is None:
            return None
        merged_tags = list(dict.fromkeys([*source.tags, *(tags or [])]))
        return self.retain(
            content=content if content is not None else source.content,
            type=type,
            session_id=session_id or source.session_id,
            source=source.source,
            importance=importance,
            tags=merged_tags,
            promoted_from=ref_id,
        )

    def consolidate(
        self,
        session_id: str | None = None,
        limit: int = 20,
        purge: bool = True,
    ) -> dict[str, Any]:
        """Run a consolidation pass and return promotion candidates.

        1. Purge expired short-term / working memories (``purge=True``).
        2. Rank the surviving short-term and working memories that have not
           been promoted yet by ``importance * (1 + access_count)`` — the
           memories the agent kept coming back to — and return the top
           ``limit`` as candidates for :meth:`promote`.

        This is deliberately LLM-free: the server does the bookkeeping, the
        agent does the synthesis (see docs/architecture/memory-tiers.md).
        """
        purged = self.forget_expired() if purge else 0
        where: dict[str, Any] | None = {"session_id": session_id} if session_id else None
        all_memories = self._vector_store.list_all(where)
        promoted_sources = {m.promoted_from for m in all_memories if m.promoted_from}
        candidates = [
            m
            for m in all_memories
            if m.tier != MemoryTier.LONG_TERM and m.ref_id not in promoted_sources and not m.checkpoint
        ]
        candidates.sort(key=lambda m: m.importance * (1 + m.access_count), reverse=True)
        preview_len = self._settings.preview_length
        return {
            "purged": purged,
            "candidates": [
                {
                    "ref_id": m.ref_id,
                    "type": m.type.value,
                    "tier": m.tier.value,
                    "importance": m.importance,
                    "access_count": m.access_count,
                    "timestamp": m.timestamp.isoformat(),
                    "preview": m.content[:preview_len],
                }
                for m in candidates[:limit]
            ],
        }

    def forget_expired(self) -> int:
        """Delete every memory whose retention window has lapsed. Returns the number deleted."""
        deleted = 0
        for memory in self._vector_store.list_all():
            if (
                memory.tier != MemoryTier.LONG_TERM
                and memory_is_expired(memory, self._settings)
                and self.forget(memory.ref_id)
            ):
                deleted += 1
        return deleted

    def forget(self, ref_id: str) -> bool:
        """Delete a memory from all stores.

        Returns True if the memory existed and was deleted, False otherwise.
        BM25 removal failure is non-fatal — the index is marked for rebuild.
        """
        canonical = self._vector_store.get_by_id(ref_id)
        if canonical is not None:
            # CODE canonical records: delete the linked chunk records first.
            for chunk_ref in canonical.chunk_refs:
                self._delete_record(chunk_ref)
            # DOCUMENT summary records: delete the body and chunks the document store keeps.
            if canonical.document_id and not _is_document_part(canonical):
                for part in self._vector_store.list_all({"document_id": canonical.document_id}):
                    if part.ref_id != ref_id:
                        self._delete_record(part.ref_id)

        return self._delete_record(ref_id)

    def _delete_record(self, ref_id: str) -> bool:
        """Delete one record from the vector store and the BM25 index."""
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
        """Rebuild the BM25 index from scratch using the vector store as source of truth.

        Document bodies are left out: their chunks are indexed instead.
        """
        all_memories = self._vector_store.list_all()
        documents = [(m.ref_id, m.content) for m in all_memories if DOCUMENT_BODY_TAG not in m.tags]
        self._sparse_index.rebuild(documents)

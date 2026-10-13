# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""MemoryService — primary domain service for retain/recall/get/forget."""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from memkernel.core.models import (
    ASK_MODES,
    CODE_CHUNK_KEY,
    CODE_CHUNK_TAG,
    DEFAULT_ASK_MODE,
    DEFAULT_IMPORTANCE,
    DOCUMENT_BODY_TAG,
    DOCUMENT_CHUNK_TAG,
    DOCUMENT_PART_KEY,
    HEALTH_CATEGORIES,
    HEALTH_DANGLING_LINKS,
    HEALTH_EXPIRED_PRESENT,
    HEALTH_NEAR_DUPLICATES,
    HEALTH_NEEDS_REVIEW,
    HEALTH_ORPHANS,
    HEALTH_STALE_SOURCES,
    HEALTH_UNMARKED_SUPERSESSIONS,
    LONG_TERM_TYPE_VALUES,
    NEEDS_REVIEW_KEY,
    PARENT_REF_KEY,
    REVIEW_REASON_CHANGED,
    REVIEW_REASON_KEY,
    REVIEW_REASON_MISSING,
    SUPERSEDED_BY_KEY,
    Answer,
    ArtifactRef,
    HealthItem,
    HealthReport,
    Memory,
    MemoryTier,
    MemoryType,
    ReasonerError,
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
        ReasonerPort,
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
_MARKDOWN_SUFFIXES: frozenset[str] = frozenset({".md", ".markdown", ".mdx"})
_MARKDOWN_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$")

# consolidate(synthesize=True): the fixed instruction sent once, over the
# concatenated candidate contents, to an external reasoner (FR-009).
DISTILLATION_PROMPT = (
    "Distil these short-term memories of a coding session into durable statements worth "
    "keeping across sessions. Write one statement per line, each prefixed with its type and "
    "a colon — decision:, convention:, fact: or procedure: — and nothing else."
)
_SYNTHESIS_TYPES: frozenset[str] = frozenset(
    {MemoryType.DECISION.value, MemoryType.CONVENTION.value, MemoryType.FACT.value, MemoryType.PROCEDURE.value}
)
_DEFAULT_SYNTHESIS_TYPE = MemoryType.FACT.value
_CANDIDATE_SEPARATOR = "\n\n---\n\n"
_CHUNK_JOINER = "\n\n"
# A list marker is a bullet or "1." / "1)" followed by whitespace; a bare
# leading number ("3 retries", "1.5s") is part of the statement.
_LIST_MARKER_RE = re.compile(r"^(?:[-*•]|\d{1,3}[.)])(?:\s+|$)")


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


def _is_code_chunk(memory: Memory, referenced: frozenset[str] = frozenset()) -> bool:
    """True for a chunk record of a `code` memory.

    Tagged or owner-linked (0.4), or referenced by a canonical's ``chunk_refs`` (legacy).
    """
    return CODE_CHUNK_TAG in memory.tags or memory.parent_ref is not None or memory.ref_id in referenced


_CODE_CHUNK_INFIX = "-chunk-"


def _code_chunk_id(parent_ref: str, position: int) -> str:
    return f"{parent_ref}{_CODE_CHUNK_INFIX}{position}"


def _document_headings(lines: list[str], name: str) -> list[str]:
    """Markdown headings (``#`` to ``######`` followed by a space) of a markdown or extension-less document.

    Code and config files use ``#`` for comments, so they get no outline.
    """
    suffix = PurePosixPath(name).suffix.lower()
    if suffix and suffix not in _MARKDOWN_SUFFIXES:
        return []
    return [m.group(1).strip() for ln in lines if (m := _MARKDOWN_HEADING_RE.match(ln)) and m.group(1).strip()]


def _document_summary(content: str, name: str, chunk_count: int, max_chars: int) -> str:
    """First ``max_chars`` of the body plus one bounded line with line count and outline."""
    lines = content.splitlines()
    headings = _document_headings(lines, name)
    outline = f"[document {name}: {len(lines)} lines, {len(content)} chars, {chunk_count} chunks"
    if headings:
        outline += "; outline: " + ", ".join(headings)
    outline = outline[: _SUMMARY_OUTLINE_MAX_CHARS - 1] + "…" if len(outline) > _SUMMARY_OUTLINE_MAX_CHARS else outline
    return content[:max_chars] + _SUMMARY_SEPARATOR + outline + "]"


def parse_suggestions(text: str) -> list[dict[str, str]]:
    """Parse one statement per line, optionally prefixed ``<type>:``, into ``{content, type}`` dicts.

    A leading list marker (``- ``, ``* ``, ``1. ``, ``1) ``) is stripped; a bare
    leading number is kept. Unknown or missing types default to ``fact``; empty
    statements are dropped.
    """
    suggested: list[dict[str, str]] = []
    for raw in text.splitlines():
        line = _LIST_MARKER_RE.sub("", raw.strip(), count=1).strip()
        if not line:
            continue
        memory_type = _DEFAULT_SYNTHESIS_TYPE
        head, sep, tail = line.partition(":")
        if sep and head.strip().lower() in _SYNTHESIS_TYPES:
            memory_type, line = head.strip().lower(), tail.strip()
        if line:
            suggested.append({"content": line, "type": memory_type})
    return suggested


def _matches_query(memory: Memory, query: SearchQuery) -> bool:
    """True when ``memory`` satisfies the metadata filters of ``query``."""
    if query.type_filter is not None and memory.type != query.type_filter:
        return False
    if query.tier_filter is not None and memory.tier != query.tier_filter:
        return False
    if query.session_id_filter is not None and memory.session_id != query.session_id_filter:
        return False
    return not (query.checkpoint_only and not memory.checkpoint)


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
        reasoner: ReasonerPort | None = None,
        synthesizer: ReasonerPort | None = None,
        fallback_reasoner: ReasonerPort | None = None,
        local_reasoner: bool = True,
    ) -> None:
        self._vector_store = vector_store
        self._embedding = embedding
        self._sparse_index = sparse_index
        self._search_service = search_service
        self._settings = settings
        self._chunker = chunker
        self._document_store = document_store
        self._document_chunker = document_chunker
        self._reasoner = reasoner
        # A reasoner able to distil statements (an LLM-backed one); None keeps
        # consolidate(synthesize=True) a no-op, as with the local reasoner.
        self._synthesizer = synthesizer
        # Answers ask() when ``reasoner`` raises ReasonerError (provider down,
        # failed run); None re-raises, which only happens for hand-built services.
        self._fallback_reasoner = fallback_reasoner
        # True when ``reasoner`` is the built-in retrieval-only LocalReasoner: a
        # document is then asked through its indexed chunks (document store
        # search) instead of handing the reasoner the whole body to re-chunk and
        # re-embed. An external reasoner (RLM Studio) retrieves on its own and
        # gets the body.
        self._local_reasoner = local_reasoner
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
        if type == MemoryType.CODE:
            return self._retain_code(content, session_id, checkpoint, source, extra)

        return self._retain_single(content, type, session_id, checkpoint, source, extra)

    def _retain_code(
        self,
        content: str,
        session_id: str | None,
        checkpoint: bool,
        source: str,
        extra: _ExtraMeta,
    ) -> str:
        """Store a code snapshot: canonical record plus owner-specific chunk records.

        Identity is ``(source, content_hash)`` for a sourced file and the content
        hash alone otherwise. A dedup hit refreshes the record, embeds nothing
        and *finishes* anything an earlier interrupted retain left undone
        (missing chunk records, live older snapshots), so a retry always
        converges. A changed file supersedes every live canonical for the same
        ``source``: the new record carries ``supersedes``, each old one gets
        ``superseded_by`` and loses its owned chunk records, and stays as a
        hidden record. If indexing the new snapshot's chunks fails, the
        half-written canonical is removed again before the error propagates.
        """
        resolved_session = session_id or self._settings.default_session_id
        content_hash = compute_content_hash(content)
        existing = self._vector_store.find_by_hash(content_hash, MemoryType.CODE.value, source=source or None)
        if existing is not None:
            self._refresh_existing(existing, resolved_session, checkpoint, extra)
            self._refresh_owned_chunks(existing.ref_id, resolved_session, checkpoint)
            self._index_missing_chunks(existing.ref_id, content, resolved_session, checkpoint, source, extra)
            self._supersede_other_snapshots(existing.ref_id, source)
            return existing.ref_id

        ref_id = self._retain_single(content, MemoryType.CODE, session_id, checkpoint, source, extra, dedup=False)
        try:
            self._index_missing_chunks(ref_id, content, resolved_session, checkpoint, source, extra)
        except Exception:
            # Compensate: a canonical without its index entries must not stay
            # findable. Best effort — the canonical goes first so that a store
            # failing mid-compensation leaves orphan chunks (which recall hides
            # and health reports), never a live half-written snapshot.
            self._delete_record(ref_id)
            for chunk in self._owned_chunks(ref_id):
                try:
                    self._delete_record(chunk.ref_id)
                except Exception:
                    logger.warning("could not remove chunk %s while compensating a failed retain", chunk.ref_id)
            raise
        self._supersede_other_snapshots(ref_id, source)
        return ref_id

    def _index_missing_chunks(
        self, ref_id: str, content: str, session_id: str, checkpoint: bool, source: str, extra: _ExtraMeta
    ) -> None:
        """Write the owned chunk records of ``ref_id`` unless the index is complete (idempotent).

        ``chunk_refs`` on the canonical is the completion marker: it is written
        last, after every chunk record, so a partial index from an interrupted
        retain has no ``chunk_refs`` and is rebuilt from scratch.
        """
        if self._chunker is None:
            return
        canonical = self._vector_store.get_by_id(ref_id)
        if canonical is None or canonical.chunk_refs:
            return
        for partial in self._owned_chunks(ref_id):
            self._delete_record(partial.ref_id)
        chunks = self._chunker.chunk(content, {"source": source})
        chunk_ids = self._index_code_chunks(ref_id, chunks, session_id, checkpoint, source, extra)
        if chunk_ids:
            self._vector_store.update_metadata(ref_id, {"chunk_refs": ",".join(chunk_ids)})

    def _supersede_other_snapshots(self, ref_id: str, source: str) -> None:
        """Make ``ref_id`` the only live snapshot of ``source`` (idempotent; a no-op without a source).

        Every other live canonical is marked first, then loses its owned chunk
        records, so an interruption between the two steps leaves a state a
        retry completes rather than one with two live snapshots.
        """
        if not source:
            return
        others = [m for m in self._live_code_canonicals(source) if m.ref_id != ref_id]
        if not others:
            return
        canonical = self._vector_store.get_by_id(ref_id)
        other_ids = {m.ref_id for m in others}
        if canonical is not None and canonical.supersedes not in other_ids:
            # point the provenance link at the newest snapshot this one replaces
            newest = max(others, key=lambda m: m.timestamp)
            self._vector_store.update_metadata(ref_id, {"supersedes": newest.ref_id})
        for old in others:
            self._mark_superseded(old.ref_id, ref_id)
        for old in others:
            self._delete_owned_chunks(old)

    def _live_code_canonicals(self, source: str) -> list[Memory]:
        """Live (not superseded) canonical `code` records for ``source``, chunk records excluded."""
        where = {"$and": [{"type": MemoryType.CODE.value}, {"source": source}]}
        records = self._vector_store.list_all(where, include_content=False)
        referenced = frozenset(ref for m in records for ref in m.chunk_refs)
        return [m for m in records if m.superseded_by is None and not _is_code_chunk(m, referenced)]

    def _index_code_chunks(
        self,
        parent_ref: str,
        chunks: list[str],
        session_id: str,
        checkpoint: bool,
        source: str,
        extra: _ExtraMeta,
    ) -> list[str]:
        """Write one owner-specific chunk record per chunk (no dedup) and return their ids."""
        chunks = [c for c in chunks if c.strip()]
        if not chunks:
            return []
        embeddings = self._embedding.embed(chunks)
        chunk_extra = _ExtraMeta(importance=extra.importance, tags=[*extra.tags, CODE_CHUNK_TAG])
        ids: list[str] = []
        for position, (chunk, embedding) in enumerate(zip(chunks, embeddings, strict=True)):
            ref_id = _code_chunk_id(parent_ref, position)
            metadata = self._new_metadata(chunk, MemoryType.CODE, session_id, checkpoint, source, chunk_extra)
            metadata[CODE_CHUNK_KEY] = True
            metadata[PARENT_REF_KEY] = parent_ref
            self._write_record(ref_id, chunk, embedding, metadata)
            ids.append(ref_id)
        return ids

    def _owned_chunks(self, parent_ref: str) -> list[Memory]:
        return self._vector_store.list_all({PARENT_REF_KEY: parent_ref}, include_content=False)

    def _refresh_owned_chunks(self, parent_ref: str, session_id: str, checkpoint: bool) -> None:
        """A dedup refresh moves the canonical to the new session: its owned chunks follow."""
        update = {"session_id": session_id, "timestamp": datetime.now(UTC).isoformat(), "checkpoint": checkpoint}
        for chunk in self._owned_chunks(parent_ref):
            if chunk.session_id != session_id or chunk.checkpoint != checkpoint:
                self._vector_store.update_metadata(chunk.ref_id, update)

    def _mark_superseded(self, target_ref: str, by_ref: str) -> None:
        """Set the durable ``superseded_by`` marker on ``target_ref`` and its owned chunks."""
        if target_ref == by_ref or self._vector_store.get_by_id(target_ref) is None:
            return
        self._vector_store.update_metadata(target_ref, {SUPERSEDED_BY_KEY: by_ref})
        for chunk in self._owned_chunks(target_ref):
            self._vector_store.update_metadata(chunk.ref_id, {SUPERSEDED_BY_KEY: by_ref})

    def _delete_owned_chunks(self, canonical: Memory) -> None:
        """Delete a canonical's owned chunk records; legacy shared chunk_refs only when nothing else references them."""
        for chunk in self._owned_chunks(canonical.ref_id):
            self._delete_record(chunk.ref_id)
        prefix = f"{canonical.ref_id}{_CODE_CHUNK_INFIX}"
        legacy = [ref for ref in canonical.chunk_refs if not ref.startswith(prefix)]
        if legacy:
            others = self._vector_store.list_all(include_content=False)
            referenced = {ref for m in others if m.ref_id != canonical.ref_id for ref in m.chunk_refs}
            for ref in legacy:
                if ref not in referenced:
                    self._delete_record(ref)

    def _retain_document(
        self,
        content: str,
        session_id: str | None,
        checkpoint: bool,
        source: str,
        extra: _ExtraMeta,
    ) -> str:
        """Store a document body + chunks through the document store; retain its summary.

        A document memory's identity is (body, ``source``), never its summary
        text: two bodies can share a summary (same prefix, size and outline),
        and one body can legitimately be retained under two names, in which
        case two summary records share one ``document_id``.
        """
        assert self._document_store is not None  # guarded by the caller
        name = source or _DEFAULT_DOCUMENT_NAME
        resolved_session = session_id or self._settings.default_session_id
        doc_id = self._document_store.put(content, name)
        doc_extra = replace(extra, document_id=doc_id)
        indexed = self._document_store.indexed(doc_id)
        existing = next((owner for owner in self._document_owners(doc_id) if owner.source == source), None)
        if indexed == 0:
            # First time this body is seen — or its chunks were lost between put
            # and index — so chunk and embed now. Otherwise nothing is embedded.
            chunks = self._document_chunker.chunk(content, {"source": name}) if self._document_chunker else [content]
            indexed = self._document_store.index(doc_id, chunks)
        if existing is not None:
            self._refresh_existing(existing, resolved_session, checkpoint, doc_extra)
            return existing.ref_id
        summary = _document_summary(content, name, indexed, self._settings.document_summary_chars)
        return self._retain_single(summary, MemoryType.DOCUMENT, session_id, checkpoint, source, doc_extra, dedup=False)

    def _document_owners(self, document_id: str) -> list[Memory]:
        """The ``document`` summary records that own ``document_id``.

        Filtered at the store: summaries are written with ``document_part: False``
        (they are new in 0.3, so no legacy store lacks the key), so the body and
        the chunk records are never loaded here.
        """
        where = {"$and": [{"document_id": document_id}, {DOCUMENT_PART_KEY: False}]}
        return self._vector_store.list_all(where)

    def _retain_single(
        self,
        content: str,
        type: MemoryType,  # noqa: A002
        session_id: str | None,
        checkpoint: bool,
        source: str,
        extra: _ExtraMeta | None = None,
        dedup: bool = True,
    ) -> str:
        """Store a single content string and return its ref_id.

        ``dedup=False`` skips the content-hash check for records whose identity
        is not their text (document summaries).
        """
        extra = extra or _ExtraMeta()
        resolved_session = session_id or self._settings.default_session_id
        content_hash = compute_content_hash(content)

        # Dedup check: same hash + same type -> update metadata, return existing id
        existing = self._vector_store.find_by_hash(content_hash, type.value) if dedup else None
        if existing is not None:
            self._refresh_existing(existing, resolved_session, checkpoint, extra)
            return existing.ref_id

        # New memory
        ref_id = str(uuid4())
        embedding = self._embedding.embed([content])[0]
        metadata = self._new_metadata(content, type, resolved_session, checkpoint, source, extra)
        self._write_record(ref_id, content, embedding, metadata)
        if extra.supersedes:
            self._mark_superseded(extra.supersedes, ref_id)
        return ref_id

    def _new_metadata(
        self,
        content: str,
        type: MemoryType,  # noqa: A002
        session_id: str,
        checkpoint: bool,
        source: str,
        extra: _ExtraMeta,
    ) -> dict[str, Any]:
        """Metadata for a brand-new record (every required key, tier and importance derived from the type)."""
        importance = extra.importance if extra.importance is not None else DEFAULT_IMPORTANCE[type]
        metadata: dict[str, Any] = {
            "project_id": self._settings.project_id,
            "session_id": session_id,
            "timestamp": datetime.now(UTC).isoformat(),
            "type": type.value,
            "tier": tier_of(type).value,
            "source": source,
            "hash": compute_content_hash(content),
            "token_count": max(1, len(content) // 4),
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
            metadata[DOCUMENT_PART_KEY] = False  # a summary record, not a body/chunk part
        return metadata

    def _write_record(self, ref_id: str, content: str, embedding: list[float], metadata: dict[str, Any]) -> None:
        """Authoritative store first; BM25 is a derived index whose failure is non-fatal."""
        self._vector_store.upsert(ref_id=ref_id, content=content, embedding=embedding, metadata=metadata)
        try:
            self._sparse_index.add(ref_id, content)
        except Exception:
            logger.warning("BM25 add failed for %s", ref_id)
            self._sparse_index.mark_needs_rebuild()

    def _refresh_existing(self, existing: Memory, session_id: str, checkpoint: bool, extra: _ExtraMeta) -> None:
        """Dedup hit: bump session/timestamp/checkpoint and merge importance, tags and supersedes."""
        update: dict[str, Any] = {
            "session_id": session_id,
            "timestamp": datetime.now(UTC).isoformat(),
            "checkpoint": checkpoint,
        }
        if extra.importance is not None:
            update["importance"] = max(existing.importance, extra.importance)
        if extra.tags:
            update["tags"] = ",".join(dict.fromkeys([*existing.tags, *extra.tags]))
        if extra.supersedes:
            update["supersedes"] = extra.supersedes
        self._vector_store.update_metadata(existing.ref_id, update)
        if extra.supersedes:
            self._mark_superseded(extra.supersedes, existing.ref_id)

    def recall(
        self,
        query: str,
        type: MemoryType | None = None,  # noqa: A002
        session_id: str | None = None,
        checkpoint_only: bool = False,
        top_k: int | None = None,
        tier: MemoryTier | None = None,
        touch: bool = True,
        include_needs_review: bool = False,
    ) -> list[ArtifactRef]:
        """Search for memories matching the query.

        Returns a list of ArtifactRef (lightweight references, no full content).
        Expired, superseded and (unless ``include_needs_review``) needs-review
        memories are filtered out from the results.
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
            live = self._filter_live(results, search_query, include_needs_review)

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

    def _filter_live(
        self, results: list[ArtifactRef], query: SearchQuery, include_needs_review: bool = False
    ) -> list[ArtifactRef]:
        """Drop expired and superseded memories; resolve document chunk hits to their summary.

        Superseded means ``superseded_by`` is set (durable, independent of the
        result window); the result-window check on ``supersedes`` links stays
        as a fallback for legacy links without the marker. The needs-review
        exclusion is applied here, in Python, never as a store filter, so a
        record without the key is simply live.

        A hit on a document body or chunk record is replaced by the document's
        summary record (the ``document`` memory) carrying the hit's score, so a
        phrase deep inside a document surfaces the document exactly once and
        chunk records never appear as top-level results. Parts are shared by
        every owner of a body and are exempt from metadata filters at search
        time, so the query's filters (type, tier, session, checkpoint) are
        applied here, to the owning summary that is actually returned.
        """
        memories: dict[str, Memory] = {}
        for ref in results:
            memory = self._vector_store.get_by_id(ref.ref_id)
            if memory is not None:
                memories[ref.ref_id] = memory
        superseded = {m.supersedes for m in memories.values() if m.supersedes}
        summaries: dict[str, Memory | None] = {}
        owners: dict[str, Memory | None] = {}
        live: list[ArtifactRef] = []
        seen: set[str] = set()
        for ref in results:
            memory = memories.get(ref.ref_id)
            if memory is None or memory.superseded_by:
                continue
            if memory.needs_review and not include_needs_review:
                continue
            if memory.parent_ref:
                # A code chunk lives and dies with its owner: dropped when the
                # owner is gone, superseded or flagged for review.
                if memory.parent_ref not in owners:
                    owners[memory.parent_ref] = self._vector_store.get_by_id(memory.parent_ref)
                owner = owners[memory.parent_ref]
                if owner is None or owner.superseded_by or (owner.needs_review and not include_needs_review):
                    continue
                if not _matches_query(owner, query):
                    continue  # the query's filters apply to the owner the chunk stands for
            if memory.document_id and _is_document_part(memory):
                if memory.document_id not in summaries:
                    summaries[memory.document_id] = self._document_summary_record(memory.document_id, query)
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

    def _document_summary_record(self, document_id: str, query: SearchQuery) -> Memory | None:
        """Return the first live ``document`` summary owning ``document_id`` that satisfies ``query``'s filters.

        A superseded summary is never resolved to: the liveness check ran on the
        chunk, not on the owner it stands for.
        """
        for owner in self._document_owners(document_id):
            if owner.superseded_by is None and _matches_query(owner, query):
                return owner
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
        """Return the number of memories in this project (document bodies and chunks excluded)."""
        return self._vector_store.count() - self._vector_store.count(where={DOCUMENT_PART_KEY: True})

    def list_memories(
        self,
        tier: MemoryTier | None = None,
        type: MemoryType | None = None,  # noqa: A002
        session_id: str | None = None,
        include_superseded: bool = False,
    ) -> list[Memory]:
        """Return memories matching the given filters (no ranking, no access tracking).

        ``tier`` is filtered in Python because records written before tiers
        existed carry no ``tier`` metadata; the adapter derives it from the type.
        Records with ``superseded_by`` set are left out unless ``include_superseded``.
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
        if not include_superseded:
            memories = [m for m in memories if m.superseded_by is None]
        if tier is not None:
            memories = [m for m in memories if m.tier == tier]
        return memories

    @property
    def project_id(self) -> str:
        """Return the project_id for this service instance."""
        return self._settings.project_id

    def stats(self) -> dict[str, object]:
        """Return total count, per-type breakdown, memory growth, and last recall timing.

        Document bodies and chunks are implementation records of one ``document``
        memory and are not counted.
        """
        all_memories = [m for m in self._vector_store.list_all() if not _is_document_part(m)]
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

    def ask(self, ref_id: str, question: str, mode: str = DEFAULT_ASK_MODE) -> Answer | None:
        """Answer ``question`` about one memory through the configured ReasonerPort.

        For a ``document`` memory an external reasoner gets the full body from
        the document store, while the built-in local reasoner gets the indexed
        chunks that best match the question (the summary is used only if the
        body is gone); any other memory is asked about its own content.
        ``mode`` is one of ``direct``, ``rag``, ``rlm``, ``auto`` and is passed
        to the reasoner unchanged. Asking
        records an access. Returns None when ``ref_id`` does not exist. When
        the reasoner raises :class:`ReasonerError` the fallback reasoner answers
        instead (``usage["fallback"] == 1``, warning logged); without a fallback
        the error propagates.
        """
        if mode not in ASK_MODES:
            raise ValueError(f"unknown ask mode {mode!r}; expected one of {', '.join(ASK_MODES)}")
        if self._reasoner is None:
            raise RuntimeError("ask() requires a ReasonerPort; build the service through build_service()")
        memory = self._vector_store.get_by_id(ref_id)
        if memory is None:
            return None
        is_document = (
            memory.type == MemoryType.DOCUMENT and bool(memory.document_id) and self._document_store is not None
        )
        content = (
            self._document_content(memory, question, chunks=self._local_reasoner) if is_document else memory.content
        )
        try:
            answer = self._reasoner.ask(content, question, mode)
        except ReasonerError as exc:
            if self._fallback_reasoner is None:
                raise
            logger.warning("ask(%s): reasoner failed (%s); answering with the fallback reasoner", ref_id, exc)
            if is_document:
                content = self._document_content(memory, question, chunks=True)
            answer = self._fallback_reasoner.ask(content, question, mode)
            answer = answer.model_copy(update={"usage": {**answer.usage, "fallback": 1}})
        self._touch(ref_id)
        return answer

    def _document_content(self, memory: Memory, question: str, chunks: bool) -> str:
        """The text a reasoner sees for a document: its best indexed chunks (``chunks``) or the whole body."""
        assert self._document_store is not None and memory.document_id  # guarded by the caller
        if chunks:
            best = self._document_store.search(memory.document_id, question, self._settings.ask_top_k)
            if best:
                return _CHUNK_JOINER.join(best)
        body = self._document_store.get(memory.document_id)
        if body is None:
            logger.warning(
                "document body %s missing for %s; asking about the summary", memory.document_id, memory.ref_id
            )
            return memory.content
        return body

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
        synthesize: bool = False,
        revalidate: bool = False,
    ) -> dict[str, Any]:
        """Run a consolidation pass and return promotion candidates.

        ``revalidate=True`` first runs :meth:`revalidate` and adds its report
        under ``"revalidated"``.

        1. Purge expired short-term / working memories (``purge=True``).
        2. Rank the surviving short-term and working memories that have not
           been promoted yet by ``importance * (1 + access_count)`` — the
           memories the agent kept coming back to — and return the top
           ``limit`` as candidates for :meth:`promote`.
        3. With ``synthesize=True`` and an external reasoner configured, ask
           it once to distil the candidates into long-term statements,
           returned under ``"suggested"`` as ``{"content", "type"}`` items
           (empty with the local reasoner, which cannot synthesise).

        Without ``synthesize`` this is deliberately LLM-free: the server does
        the bookkeeping, the agent does the synthesis (see
        docs/architecture/memory-tiers.md).
        """
        revalidated = self.revalidate() if revalidate else None
        purged = self.forget_expired() if purge else 0
        where: dict[str, Any] | None = {"session_id": session_id} if session_id else None
        all_memories = self._vector_store.list_all(where)
        promoted_sources = {m.promoted_from for m in all_memories if m.promoted_from}
        candidates = [
            m
            for m in all_memories
            if m.tier != MemoryTier.LONG_TERM
            and m.ref_id not in promoted_sources
            and not m.checkpoint
            and m.superseded_by is None
        ]
        candidates.sort(key=lambda m: m.importance * (1 + m.access_count), reverse=True)
        top = candidates[:limit]
        preview_len = self._settings.preview_length
        suggested: list[dict[str, str]] = []
        if synthesize and top and self._synthesizer is not None:
            bundle = _CANDIDATE_SEPARATOR.join(m.content for m in top)
            try:
                answer = self._synthesizer.ask(bundle, DISTILLATION_PROMPT, DEFAULT_ASK_MODE)
            except ReasonerError as exc:
                logger.warning("consolidate(synthesize=True): reasoner failed, no suggestions: %s", exc)
            else:
                suggested = parse_suggestions(answer.answer)
        report: dict[str, Any] = {
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
                for m in top
            ],
            "suggested": suggested,
        }
        if revalidated is not None:
            report["revalidated"] = revalidated
        report["health"] = self.health(full=False).summary
        return report

    # ------------------------------------------------------------------
    # Store health (0.4) — read-only
    # ------------------------------------------------------------------

    def health(self, full: bool = True) -> HealthReport:
        """Audit the store without changing it.

        Quick mode (``full=False``) reads ids and metadata only and reports
        orphans, dangling links, unmarked supersessions, stale sources,
        needs-review and expired-but-present records. Full mode also loads
        content to find near-duplicate pairs among the most recent live
        long-term memories (bounded by ``health_duplicate_limit``).
        """
        limit = self._settings.health_report_limit
        records = self._vector_store.list_all(include_content=full)
        by_id = {m.ref_id: m for m in records}
        referenced = frozenset(ref for m in records for ref in m.chunk_refs)
        counts: dict[str, int] = dict.fromkeys(HEALTH_CATEGORIES, 0)
        items: dict[str, list[HealthItem]] = {category: [] for category in HEALTH_CATEGORIES}

        def add(category: str, ref_id: str, detail: str) -> None:
            counts[category] += 1
            if len(items[category]) < limit:
                items[category].append(HealthItem(ref_id=ref_id, detail=detail))

        owners = {m.document_id for m in records if m.document_id and not _is_document_part(m)}
        for m in records:
            if _is_document_part(m) and m.document_id not in owners:
                add(HEALTH_ORPHANS, m.ref_id, f"document part of {m.document_id} with no owning summary")
            elif m.parent_ref and m.parent_ref not in by_id:
                add(HEALTH_ORPHANS, m.ref_id, f"code chunk of missing canonical {m.parent_ref}")
            for name in ("supersedes", "superseded_by", "promoted_from", "parent_ref"):
                target = getattr(m, name)
                if target and target not in by_id:
                    add(HEALTH_DANGLING_LINKS, m.ref_id, f"{name} -> {target} (missing)")
            if m.supersedes and m.supersedes in by_id and by_id[m.supersedes].superseded_by is None:
                add(HEALTH_UNMARKED_SUPERSESSIONS, m.supersedes, f"superseded by {m.ref_id} without superseded_by")
            is_chunk = _is_code_chunk(m, referenced)
            if m.type == MemoryType.CODE and m.source and not is_chunk and m.superseded_by is None:
                path = self._resolve_source(m.source)
                if path is not None and not path.is_file():
                    add(HEALTH_STALE_SOURCES, m.ref_id, f"{m.source} does not exist")
            if m.needs_review and not is_chunk and not _is_document_part(m):
                add(HEALTH_NEEDS_REVIEW, m.ref_id, f"{m.source or m.type.value}: {m.review_reason}")
            if m.tier != MemoryTier.LONG_TERM and memory_is_expired(m, self._settings):
                add(HEALTH_EXPIRED_PRESENT, m.ref_id, f"{m.type.value} expired, not yet purged")

        if full:
            # One item per pair: ref_id is the lexicographically smaller id, the
            # detail names the other one ("~ <other> (cosine 0.987)").
            for first, second, similarity in self._near_duplicates(records, referenced):
                add(HEALTH_NEAR_DUPLICATES, first, f"~ {second} (cosine {similarity:.3f})")

        return HealthReport(full=full, counts=counts, **items)

    def _near_duplicates(self, records: list[Memory], referenced: frozenset[str]) -> list[tuple[str, str, float]]:
        """Pairs of live long-term memories (chunks and parts excluded) above the similarity threshold.

        Each candidate is re-embedded and queried against the long-term *type
        values* (records written before 0.2 carry no tier label); neighbours
        outside the candidate set and pairs already linked by supersedes,
        superseded_by or promoted_from are ignored. Complete within the set.

        Pair contract: every pair is returned once as ``(first, second, score)``
        with ``first < second`` lexicographically (no "which is the original"
        meaning), and ``score`` is the best of the two query directions, so an
        approximate index scoring one direction below the threshold cannot
        drop a pair the other direction clears.
        """
        candidates = [
            m
            for m in records
            if m.tier == MemoryTier.LONG_TERM
            and m.superseded_by is None
            and not _is_document_part(m)
            and not _is_code_chunk(m, referenced)
            and m.content
        ]
        candidates.sort(key=lambda m: m.timestamp, reverse=True)
        candidates = candidates[: self._settings.health_duplicate_limit]
        if len(candidates) < 2:
            return []
        in_set = {m.ref_id for m in candidates}
        linked: set[frozenset[str]] = set()
        for m in records:
            for target in (m.supersedes, m.superseded_by, m.promoted_from):
                if target:
                    linked.add(frozenset((m.ref_id, target)))
        threshold = self._settings.health_duplicate_threshold
        where: dict[str, Any] = {"type": {"$in": list(LONG_TERM_TYPE_VALUES)}}
        # Every long-term record (superseded ones, chunks, parts) competes for
        # result slots, so ask for all of them: completeness within the
        # candidate set needs the whole neighbourhood, not the top few.
        top_k = max(2, self._vector_store.count(where=where))
        embeddings = self._embedding.embed([m.content for m in candidates])
        pairs: dict[frozenset[str], float] = {}
        for memory, embedding in zip(candidates, embeddings, strict=True):
            for hit in self._vector_store.search_dense(embedding, top_k, where):
                if hit.ref_id == memory.ref_id or hit.ref_id not in in_set or hit.score < threshold:
                    continue
                key = frozenset((memory.ref_id, hit.ref_id))
                if key in linked:
                    continue
                pairs[key] = max(pairs.get(key, 0.0), hit.score)
        return sorted((min(k), max(k), score) for k, score in pairs.items())

    # ------------------------------------------------------------------
    # Revalidation of code memories (0.4)
    # ------------------------------------------------------------------

    def _resolve_source(self, source: str) -> Path | None:
        """Resolve ``source`` inside the project root; None when it escapes the boundary.

        Relative paths join ``project_root``; absolute paths are taken as given;
        symlinks are followed and ``..`` normalised before the containment check,
        so nothing outside the resolved root is ever read.
        """
        root = Path(self._settings.project_root).resolve()
        candidate = Path(source) if Path(source).is_absolute() else root / source
        try:
            resolved = candidate.resolve()
        except OSError:
            return None
        return resolved if resolved.is_relative_to(root) else None

    def revalidate(self) -> dict[str, Any]:
        """Compare every live canonical `code` memory with its source file; flag or clear ``needs_review``.

        Whole-file hashing: the file's content hash (the same one retain uses)
        against the stored ``content_hash``. A missing file flags ``missing``, a
        different hash flags ``changed``, a matching file clears a flag; owned
        chunk records follow their canonical. Paths outside the project root
        or unreadable count as ``unknown`` and are left untouched. Nothing else
        is written.
        """
        report: dict[str, Any] = {"checked": 0, "changed": 0, "missing": 0, "cleared": 0, "unknown": 0, "flagged": []}
        records = self._vector_store.list_all({"type": MemoryType.CODE.value}, include_content=False)
        referenced = frozenset(ref for m in records for ref in m.chunk_refs)
        for memory in records:
            if memory.superseded_by or not memory.source or _is_code_chunk(memory, referenced):
                continue
            report["checked"] += 1
            path = self._resolve_source(memory.source)
            if path is None:
                report["unknown"] += 1
                continue
            if not path.is_file():
                reason = REVIEW_REASON_MISSING
            else:
                try:
                    text = path.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    report["unknown"] += 1
                    continue
                reason = REVIEW_REASON_CHANGED if compute_content_hash(text) != memory.content_hash else ""
            if reason:
                report[reason] += 1
                report["flagged"].append({"ref_id": memory.ref_id, "source": memory.source, "reason": reason})
                if not (memory.needs_review and memory.review_reason == reason):
                    self._set_review(memory.ref_id, True, reason)
            elif memory.needs_review:
                report["cleared"] += 1
                self._set_review(memory.ref_id, False, "")
        return report

    def _set_review(self, ref_id: str, flag: bool, reason: str) -> None:
        """Write the review flag on a canonical and on its owned chunk records."""
        update = {NEEDS_REVIEW_KEY: flag, REVIEW_REASON_KEY: reason}
        self._vector_store.update_metadata(ref_id, update)
        for chunk in self._owned_chunks(ref_id):
            self._vector_store.update_metadata(chunk.ref_id, update)

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
            # CODE canonical records: delete the owned chunk records first
            # (legacy shared chunks only when nothing else references them).
            self._delete_owned_chunks(canonical)
            # DOCUMENT summary records: delete the body and chunks the document store
            # keeps — but only when no other summary (same body, other name) still owns them.
            if canonical.document_id and not _is_document_part(canonical):
                parts = self._vector_store.list_all({"document_id": canonical.document_id})
                other_owners = [p for p in parts if not _is_document_part(p) and p.ref_id != ref_id]
                if not other_owners:
                    for part in parts:
                        if _is_document_part(part):
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

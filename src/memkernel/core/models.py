# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""Domain models for MemKernel.

Memory is organised in three tiers (see docs/architecture/memory-tiers.md):

* ``working``    — the agent's scratchpad for the current task. Session-scoped,
                   expires within hours. Cognitive analogue: working memory.
* ``short_term`` — episodic memory: what happened, what was observed. Subject
                   to decay; frequently recalled items survive longer.
* ``long_term``  — semantic and procedural memory: decisions, conventions,
                   facts, procedures, code understanding. Never expires; curated
                   through consolidation and (optionally) an LLM wiki.

Each :class:`MemoryType` belongs to exactly one tier (``TYPE_TIER``), so callers
only choose a type; the tier, default importance and decay policy follow.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class MemoryTier(StrEnum):
    """Lifecycle tier of a memory. Drives decay policy and recall weighting."""

    WORKING = "working"
    SHORT_TERM = "short_term"
    LONG_TERM = "long_term"


class MemoryType(StrEnum):
    """Classification of stored memories. Determines tier, importance and TTL policy."""

    # Long-term, semantic
    DECISION = "decision"
    CONVENTION = "convention"
    FACT = "fact"
    CODE = "code"
    # Long-term, procedural
    PROCEDURE = "procedure"
    # Long-term, a large artefact whose body lives in the document store (ADR-009)
    DOCUMENT = "document"
    # Short-term, episodic
    EPISODE = "episode"
    OBSERVATION = "observation"
    # Working memory
    TASK = "task"


TYPE_TIER: dict[MemoryType, MemoryTier] = {
    MemoryType.DECISION: MemoryTier.LONG_TERM,
    MemoryType.CONVENTION: MemoryTier.LONG_TERM,
    MemoryType.FACT: MemoryTier.LONG_TERM,
    MemoryType.CODE: MemoryTier.LONG_TERM,
    MemoryType.PROCEDURE: MemoryTier.LONG_TERM,
    MemoryType.DOCUMENT: MemoryTier.LONG_TERM,
    MemoryType.EPISODE: MemoryTier.SHORT_TERM,
    MemoryType.OBSERVATION: MemoryTier.SHORT_TERM,
    MemoryType.TASK: MemoryTier.WORKING,
}

# Default importance (0..1) when the caller does not supply one.
# Mirrors the "importance" axis of Generative Agents (Park et al., 2023):
# durable, high-consequence knowledge scores high; raw observations score low.
DEFAULT_IMPORTANCE: dict[MemoryType, float] = {
    MemoryType.DECISION: 0.9,
    MemoryType.CONVENTION: 0.9,
    MemoryType.PROCEDURE: 0.8,
    MemoryType.FACT: 0.7,
    MemoryType.CODE: 0.6,
    MemoryType.DOCUMENT: 0.6,
    MemoryType.TASK: 0.5,
    MemoryType.EPISODE: 0.4,
    MemoryType.OBSERVATION: 0.3,
}


# Tags that mark the records a document store keeps beside the memkernel summary
# record: the canonical body and its indexed chunks. Both are hidden from
# top-level recall / list results; a chunk hit resolves to the document summary.
DOCUMENT_BODY_TAG = "document_body"
DOCUMENT_CHUNK_TAG = "document_chunk"


def tier_of(memory_type: MemoryType) -> MemoryTier:
    """Return the tier a memory type belongs to."""
    return TYPE_TIER[memory_type]


class Memory(BaseModel):
    """A stored unit of knowledge with full content and metadata."""

    ref_id: str
    content: str
    type: MemoryType
    project_id: str
    session_id: str
    timestamp: datetime
    source: str = ""
    content_hash: str
    token_count: int
    checkpoint: bool = False
    chunk_refs: list[str] = []
    # Tiered-memory metadata (all optional for backward compatibility with
    # records written by memkernel 0.1.x, which carry none of these).
    tier: MemoryTier = MemoryTier.LONG_TERM
    importance: float = Field(default=0.5, ge=0.0, le=1.0)
    access_count: int = 0
    last_accessed: datetime | None = None
    tags: list[str] = []
    supersedes: str | None = None
    promoted_from: str | None = None
    # Set on a ``document`` summary record and on the body/chunk records the
    # document store keeps for it (ADR-009).
    document_id: str | None = None


class Answer(BaseModel):
    """Result of ``ask``: the answer text, the reasoning mode actually used, and provenance."""

    answer: str
    mode: str
    citations: list[str] = []
    usage: dict[str, float | int] = {}


class ArtifactRef(BaseModel):
    """Lightweight reference returned by recall — no full content.

    Matches spec FR-003: ref_id, preview, score, token_count, type, timestamp.
    No checkpoint field — checkpoint filtering is query-side via checkpoint_only param.
    ``tier`` and ``importance`` are included so the caller can see why a result
    ranked where it did without a second round trip.
    """

    ref_id: str
    preview: str
    score: float
    token_count: int
    type: MemoryType
    timestamp: datetime
    tier: MemoryTier = MemoryTier.LONG_TERM
    importance: float = 0.5


class SearchResult(BaseModel):
    """Internal pre-fusion search result from a single source."""

    ref_id: str
    score: float
    rank: int


class SearchQuery(BaseModel):
    """Internal query representation for HybridSearchService."""

    query_text: str
    type_filter: MemoryType | None = None
    tier_filter: MemoryTier | None = None
    session_id_filter: str | None = None
    checkpoint_only: bool = False
    top_k: int = 5

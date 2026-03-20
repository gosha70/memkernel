# Copyright (c) EGOGE - All Rights Reserved.
# This software may be used and distributed according to the terms of the MIT license.
"""Domain models for MemKernel."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel


class MemoryType(StrEnum):
    """Classification of stored memories. Controls TTL policy."""

    DECISION = "decision"
    CONVENTION = "convention"
    CODE = "code"
    EPISODE = "episode"


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


class ArtifactRef(BaseModel):
    """Lightweight reference returned by recall — no full content.

    Matches spec FR-003: ref_id, preview, score, token_count, type, timestamp.
    No checkpoint field — checkpoint filtering is query-side via checkpoint_only param.
    """

    ref_id: str
    preview: str
    score: float
    token_count: int
    type: MemoryType
    timestamp: datetime


class SearchResult(BaseModel):
    """Internal pre-fusion search result from a single source."""

    ref_id: str
    score: float
    rank: int


class SearchQuery(BaseModel):
    """Internal query representation for HybridSearchService."""

    query_text: str
    type_filter: MemoryType | None = None
    session_id_filter: str | None = None
    checkpoint_only: bool = False
    top_k: int = 5

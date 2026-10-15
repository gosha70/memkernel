# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""MemKernel configuration via environment variables."""

from __future__ import annotations

from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class MemKernelSettings(BaseSettings):
    """All settings are configurable via MEMKERNEL_ prefixed env vars."""

    # extra="ignore": a project .env usually holds keys for other tools; they
    # must not stop the server from starting (issue #15).
    model_config = SettingsConfigDict(env_prefix="MEMKERNEL_", env_file=".env", extra="ignore")

    project_id: str = "default"
    default_session_id: str = "default"

    # ChromaDB
    chroma_persist_path: str = ".memkernel/chroma"
    chroma_collection_prefix: str = "memkernel"

    # Embedding
    embedding_model: str = "all-MiniLM-L6-v2"
    embedding_dimension: int = 384

    # Retrieval
    search_top_k: int = 5
    rrf_k: int = 60
    preview_length: int = 200

    # Chunking
    chunk_size: int = 1500  # max chars per chunk
    chunk_overlap: int = 200  # char overlap between token chunks (fallback only)

    # Documents and ask() (ADR-009)
    document_store: Literal["local"] = "local"  # where `document` bodies live
    document_summary_chars: int = 1000  # characters of the body kept in the document's summary record
    reasoner: Literal["local", "rlmstudio"] = "local"  # ReasonerPort behind ask(); falls back to local
    ask_top_k: int = 5  # chunks the local reasoner returns per ask()

    # Sources, revalidation and store health (0.4)
    project_root: str = "."  # relative `source` paths resolve under this directory; nothing outside it is read
    health_duplicate_threshold: float = (
        0.95  # cosine similarity in [0, 1] from which two long-term memories are near-duplicates
    )
    health_duplicate_limit: int = 500  # most recent long-term memories checked for near-duplicates
    health_report_limit: int = 20  # items listed per health category

    # Lifecycle / decay (see docs/architecture/memory-tiers.md)
    episode_ttl_days: int = 30  # base TTL for short-term `episode` memories
    observation_ttl_days: int = 7  # base TTL for short-term `observation` memories
    task_ttl_hours: int = 24  # base TTL for working-memory `task` records
    access_boost: float = 0.5  # each recall extends TTL by this fraction of the base TTL
    recency_half_life_days: float = 7.0  # recency decay half-life for short-term memories

    # Recall scoring: final = w_relevance * fused + w_recency * recency + w_importance * importance
    recall_weight_relevance: float = 1.0
    recall_weight_recency: float = 0.3
    recall_weight_importance: float = 0.3

    # LLM wiki bridge: directory holding the markdown wiki (index.md, decisions/, ...).
    # Empty = no wiki configured; wiki_export/wiki_import then require an explicit path.
    wiki_dir: str = ""

    # Server
    transport: Literal["stdio", "streamable-http"] = "stdio"
    host: str = "127.0.0.1"
    port: int = 8765

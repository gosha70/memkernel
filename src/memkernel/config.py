"""MemKernel configuration via environment variables."""

from __future__ import annotations

from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class MemKernelSettings(BaseSettings):
    """All settings are configurable via MEMKERNEL_ prefixed env vars."""

    model_config = SettingsConfigDict(env_prefix="MEMKERNEL_", env_file=".env")

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

    # TTL
    episode_ttl_days: int = 30

    # Server
    transport: Literal["stdio", "streamable-http"] = "stdio"
    host: str = "127.0.0.1"
    port: int = 8765

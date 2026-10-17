# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""MemKernel configuration via environment variables."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Literal

from pydantic_settings import BaseSettings, EnvSettingsSource, PydanticBaseSettingsSource, SettingsConfigDict

if TYPE_CHECKING:
    from pydantic.fields import FieldInfo

logger = logging.getLogger(__name__)

ENV_PREFIX = "MEMKERNEL_"
ENV_FILE = ".env"


class MemKernelSettings(BaseSettings):
    """All settings are configurable via MEMKERNEL_ prefixed env vars."""

    # Unknown keys stay forbidden (constructor typos raise), but the .env source
    # is filtered to known settings: a project .env usually holds keys for other
    # tools and must not stop the server from starting (issue #15). Misspelled
    # MEMKERNEL_ keys are reported by settings_customise_sources().
    model_config = SettingsConfigDict(env_prefix=ENV_PREFIX, env_file=ENV_FILE)

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
    # Where wiki-studio patch-sets are written before promote (memkernel[wiki], ADR-010).
    # Empty = <project_root>/.memkernel/wiki-proposals; set it to request the gate explicitly.
    wiki_proposals_dir: str = ""

    # Server
    transport: Literal["stdio", "streamable-http"] = "stdio"
    host: str = "127.0.0.1"
    port: int = 8765

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Default source order with the .env source limited to known settings.

        Warns about MEMKERNEL_ keys in the environment or in .env that match no setting.
        """
        for source, origin in ((env_settings, "the environment"), (dotenv_settings, ENV_FILE)):
            for key in unknown_prefixed_keys(settings_cls, source):
                logger.warning(
                    "memkernel: unknown setting %s in %s is ignored; check the spelling against the README", key, origin
                )
        return init_settings, env_settings, KnownFieldsOnly(dotenv_settings), file_secret_settings


class KnownFieldsOnly(PydanticBaseSettingsSource):
    """Pass through only the values of ``inner`` that belong to a settings field."""

    def __init__(self, inner: PydanticBaseSettingsSource) -> None:
        super().__init__(inner.settings_cls)
        self._inner = inner

    def get_field_value(self, field: FieldInfo, field_name: str) -> tuple[Any, str, bool]:
        return self._inner.get_field_value(field, field_name)

    def __call__(self) -> dict[str, Any]:
        return {key: value for key, value in self._inner().items() if key in self.settings_cls.model_fields}


def unknown_prefixed_keys(settings_cls: type[BaseSettings], source: PydanticBaseSettingsSource) -> list[str]:
    """Return the MEMKERNEL_ keys ``source`` holds that are not fields of ``settings_cls``, upper-cased."""
    if not isinstance(source, EnvSettingsSource):
        return []
    prefix = ENV_PREFIX.lower()  # case-insensitive sources expose lower-cased keys
    return sorted(
        key.upper()
        for key in source.env_vars
        if key.lower().startswith(prefix) and key.lower()[len(prefix) :] not in settings_cls.model_fields
    )

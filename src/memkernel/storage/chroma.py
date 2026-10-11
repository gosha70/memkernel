# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""ChromaDB adapter implementing VectorStorePort."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import chromadb

from memkernel.core.models import DEFAULT_IMPORTANCE, Memory, MemoryTier, MemoryType, SearchResult, tier_of

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from chromadb.api import ClientAPI
    from chromadb.api.models.Collection import Collection

    from memkernel.config import MemKernelSettings


_REQUIRED_METADATA_KEYS: frozenset[str] = frozenset(
    {"project_id", "session_id", "timestamp", "type", "source", "hash", "token_count"}
)


def _to_chroma_metadata(metadata: dict[str, Any]) -> dict[str, str | int | float | bool]:
    """Normalise a metadata dict to ChromaDB-acceptable scalar types."""
    result: dict[str, str | int | float | bool] = {}
    for key, value in metadata.items():
        if isinstance(value, bool | int | float):
            result[key] = value
        elif isinstance(value, datetime):
            result[key] = value.isoformat()
        else:
            result[key] = str(value)
    return result


def _memory_from_chroma(
    ids: list[str],
    documents: list[str],
    metadatas: list[Mapping[str, Any]],
    index: int,
) -> Memory:
    """Reconstruct a Memory from ChromaDB get/query result lists."""
    meta = metadatas[index]
    raw_ts = meta.get("timestamp", "")
    timestamp = datetime.fromisoformat(str(raw_ts)) if raw_ts else datetime.now(tz=UTC)
    chunk_refs = _split_csv(meta.get("chunk_refs"))
    memory_type = MemoryType(str(meta.get("type", "episode")))
    # Records written by memkernel 0.1.x carry no tier/importance metadata;
    # derive defaults from the type so old stores keep working unchanged.
    raw_tier = meta.get("tier")
    tier = MemoryTier(str(raw_tier)) if raw_tier else tier_of(memory_type)
    raw_importance = meta.get("importance")
    importance = float(raw_importance) if raw_importance is not None else DEFAULT_IMPORTANCE[memory_type]
    raw_last = meta.get("last_accessed")
    last_accessed = datetime.fromisoformat(str(raw_last)) if raw_last else None
    return Memory(
        ref_id=ids[index],
        content=documents[index],
        type=memory_type,
        project_id=str(meta.get("project_id", "")),
        session_id=str(meta.get("session_id", "")),
        timestamp=timestamp,
        source=str(meta.get("source", "")),
        content_hash=str(meta.get("hash", "")),
        token_count=int(meta.get("token_count", 0)),
        checkpoint=bool(meta.get("checkpoint", False)),
        chunk_refs=chunk_refs,
        tier=tier,
        importance=importance,
        access_count=int(meta.get("access_count", 0) or 0),
        last_accessed=last_accessed,
        tags=_split_csv(meta.get("tags")),
        supersedes=str(meta["supersedes"]) if meta.get("supersedes") else None,
        promoted_from=str(meta["promoted_from"]) if meta.get("promoted_from") else None,
        document_id=str(meta["document_id"]) if meta.get("document_id") else None,
    )


def _split_csv(raw: Any) -> list[str]:
    """Split a comma-separated metadata value into a list (ChromaDB has no list type)."""
    if not raw:
        return []
    return [part for part in str(raw).split(",") if part]


class ChromaVectorStore:
    """ChromaDB-backed implementation of VectorStorePort.

    Production usage:
        store = ChromaVectorStore(settings)

    Test usage (in-memory, no persistence):
        store = ChromaVectorStore(settings, client=chromadb.EphemeralClient())
    """

    def __init__(
        self,
        settings: MemKernelSettings,
        client: ClientAPI | None = None,
    ) -> None:
        if client is not None:
            self._client: ClientAPI = client
        else:
            persist_path = settings.chroma_persist_path.strip()
            if persist_path:
                self._client = chromadb.PersistentClient(path=persist_path)
            else:
                self._client = chromadb.EphemeralClient()

        collection_name = f"{settings.chroma_collection_prefix}_{settings.project_id}"
        self._collection: Collection = self._client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )

    # ------------------------------------------------------------------
    # VectorStorePort methods
    # ------------------------------------------------------------------

    def upsert(
        self,
        ref_id: str,
        content: str,
        embedding: list[float],
        metadata: dict[str, Any],
    ) -> None:
        """Insert or update a memory in the collection."""
        missing = _REQUIRED_METADATA_KEYS - metadata.keys()
        if missing:
            raise ValueError(f"upsert missing required metadata keys: {sorted(missing)}")
        embeddings: list[Sequence[float]] = [embedding]
        self._collection.upsert(
            ids=[ref_id],
            embeddings=embeddings,
            documents=[content],
            metadatas=[_to_chroma_metadata(metadata)],
        )

    def search_dense(
        self,
        query_embedding: list[float],
        top_k: int,
        where: dict[str, Any] | None = None,
    ) -> list[SearchResult]:
        """Query by vector similarity. Returns results ordered by score descending."""
        query_embeddings: list[Sequence[float]] = [query_embedding]
        kwargs: dict[str, Any] = {
            "query_embeddings": query_embeddings,
            "n_results": top_k,
            "include": ["metadatas", "documents", "distances"],
        }
        if where is not None:
            kwargs["where"] = where

        results = self._collection.query(**kwargs)

        # ChromaDB returns nested lists; unpack the first (only) query row.
        ids: list[str] = (results.get("ids") or [[]])[0]
        distances: list[float] = (results.get("distances") or [[]])[0]

        search_results: list[SearchResult] = []
        for rank_idx, (ref_id, distance) in enumerate(zip(ids, distances, strict=True), start=1):
            score = 1.0 - distance
            search_results.append(SearchResult(ref_id=ref_id, score=score, rank=rank_idx))

        return search_results

    def get_by_id(self, ref_id: str) -> Memory | None:
        """Fetch a single memory by its ref_id. Returns None if not found."""
        result = self._collection.get(
            ids=[ref_id],
            include=["metadatas", "documents"],
        )
        ids: list[str] = result.get("ids") or []
        raw_docs = result.get("documents")
        documents: list[str] = list(raw_docs) if raw_docs is not None else []
        raw_metas = result.get("metadatas")
        metadatas: list[Mapping[str, Any]] = list(raw_metas) if raw_metas is not None else []

        if not ids:
            return None

        return _memory_from_chroma(ids, documents, metadatas, 0)

    def delete(self, ref_id: str) -> bool:
        """Delete a memory by ref_id. Returns True if it existed, False otherwise."""
        existing = self.get_by_id(ref_id)
        if existing is None:
            return False
        self._collection.delete(ids=[ref_id])
        return True

    def list_all(self, where: dict[str, Any] | None = None) -> list[Memory]:
        """Return all memories, optionally filtered by metadata."""
        kwargs: dict[str, Any] = {"include": ["metadatas", "documents"]}
        if where is not None:
            kwargs["where"] = where

        result = self._collection.get(**kwargs)
        ids: list[str] = result.get("ids") or []
        raw_docs = result.get("documents")
        documents: list[str] = list(raw_docs) if raw_docs is not None else []
        raw_metas = result.get("metadatas")
        metadatas: list[Mapping[str, Any]] = list(raw_metas) if raw_metas is not None else []

        return [_memory_from_chroma(ids, documents, metadatas, i) for i in range(len(ids))]

    def find_by_hash(self, content_hash: str, memory_type: str) -> Memory | None:
        """Find a memory by content hash + type. Returns first match or None."""
        result = self._collection.get(
            where={"$and": [{"hash": content_hash}, {"type": memory_type}]},
            include=["metadatas", "documents"],
        )
        ids: list[str] = result.get("ids") or []
        raw_docs = result.get("documents")
        documents: list[str] = list(raw_docs) if raw_docs is not None else []
        raw_metas = result.get("metadatas")
        metadatas: list[Mapping[str, Any]] = list(raw_metas) if raw_metas is not None else []

        if not ids:
            return None

        return _memory_from_chroma(ids, documents, metadatas, 0)

    def update_metadata(self, ref_id: str, metadata: dict[str, Any]) -> None:
        """Fetch-and-merge: caller-specified keys overwrite existing; all other keys preserved."""
        existing_result = self._collection.get(
            ids=[ref_id],
            include=["metadatas"],
        )
        existing_ids: list[str] = existing_result.get("ids") or []
        raw_existing_metas = existing_result.get("metadatas")
        existing_metadatas: list[Mapping[str, Any]] = list(raw_existing_metas) if raw_existing_metas is not None else []

        if not existing_ids:
            return

        merged: dict[str, Any] = dict(existing_metadatas[0])
        merged.update(metadata)

        self._collection.update(
            ids=[ref_id],
            metadatas=[_to_chroma_metadata(merged)],
        )

    def count(self) -> int:
        """Return the total number of memories in the collection."""
        return self._collection.count()

    def list_collections(self) -> list[dict[str, Any]]:
        """List all collections accessible via this client with their record counts."""
        return [{"name": coll.name, "count": coll.count()} for coll in self._client.list_collections()]

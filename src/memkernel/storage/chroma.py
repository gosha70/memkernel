# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""ChromaDB adapter implementing VectorStorePort."""

from __future__ import annotations

import hashlib
import logging
import os
import threading
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import chromadb
from chromadb.config import DEFAULT_DATABASE, DEFAULT_TENANT

from memkernel.core.models import (
    CODE_CHUNK_KEY,
    DEFAULT_IMPORTANCE,
    NEEDS_REVIEW_KEY,
    PARENT_REF_KEY,
    REVIEW_REASON_KEY,
    STORE_LOCK_NAMES,
    STORE_LOCK_TAGS,
    SUPERSEDED_BY_KEY,
    WITHDRAWN_AT_KEY,
    WITHDRAWN_REASON_KEY,
    LockReentryError,
    Memory,
    MemoryTier,
    MemoryType,
    SearchResult,
    tier_of,
)

try:
    import fcntl
except ImportError:  # not POSIX (e.g. Windows): a store opens unlocked, as before (store-open-race FR-003)
    fcntl = None  # type: ignore[assignment]

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping, Sequence

    from chromadb.api import ClientAPI
    from chromadb.api.models.Collection import Collection

    from memkernel.config import MemKernelSettings


logger = logging.getLogger(__name__)

# Held while a persisted store is opened, so two processes never create a new store's tables at once (#69).
OPEN_LOCK_FILE = ".memkernel-open.lock"
_unlocked_logged = False


@contextmanager
def _store_open_lock(persist_path: str) -> Iterator[None]:
    """Hold an exclusive advisory lock on ``persist_path``'s open-lock file; released on every path.

    ``flock`` is released when the file is closed and by the operating system when a process dies, so it cannot
    be left stale. Without ``fcntl`` the store opens unlocked and that is logged once at debug level.
    """
    global _unlocked_logged
    if fcntl is None:
        if not _unlocked_logged:
            logger.debug("fcntl is not available: ChromaDB stores open without the open lock")
            _unlocked_logged = True
        yield
        return
    directory = Path(persist_path)
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / OPEN_LOCK_FILE).open("a", encoding="utf-8") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


# Store locks (memkernel-0-7-store-locks): keyed by the store itself, never by a setting.
STORE_LOCK_FILE_PREFIX = ".memkernel-"
LOCK_WAIT_LOG_SECONDS = 10.0  # a take waiting longer than this logs one info line, then keeps waiting
_LOCK_POLL_SECONDS = 0.05
_STORE_KEY_HASH_CHARS = 16
TAGS_KEY = "tags"

_thread_locks: dict[tuple[str, str], threading.Lock] = {}  # serialises threads of this process, per store and name
_thread_locks_guard = threading.Lock()
_held = threading.local()  # the (store key, name) pairs the current thread holds: store locks are not re-entrant
_unlocked_warned: set[str] = set()


def _thread_lock(key: tuple[str, str]) -> threading.Lock:
    with _thread_locks_guard:
        return _thread_locks.setdefault(key, threading.Lock())


def _held_pairs() -> set[tuple[str, str]]:
    pairs: set[tuple[str, str]] | None = getattr(_held, "pairs", None)
    if pairs is None:
        pairs = set()
        _held.pairs = pairs
    return pairs


def _acquire_thread_lock(lock: threading.Lock, name: str, store: str) -> None:
    if not lock.acquire(timeout=LOCK_WAIT_LOG_SECONDS):
        logger.info("waiting for store lock %s on %s", name, store)
        lock.acquire()


@contextmanager
def _file_lock(path: Path, name: str, store: str) -> Iterator[None]:
    """Hold an exclusive ``flock`` on ``path``; polls so that a long wait is logged once, then keeps waiting."""
    with path.open("a", encoding="utf-8") as handle:
        started = time.monotonic()
        logged = False
        while True:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if not logged and time.monotonic() - started > LOCK_WAIT_LOG_SECONDS:
                    logger.info("waiting for store lock %s on %s", name, store)
                    logged = True
                time.sleep(_LOCK_POLL_SECONDS)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


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
        tags=_split_csv(meta.get(TAGS_KEY)),
        supersedes=str(meta["supersedes"]) if meta.get("supersedes") else None,
        promoted_from=str(meta["promoted_from"]) if meta.get("promoted_from") else None,
        document_id=str(meta["document_id"]) if meta.get("document_id") else None,
        superseded_by=str(meta[SUPERSEDED_BY_KEY]) if meta.get(SUPERSEDED_BY_KEY) else None,
        parent_ref=str(meta[PARENT_REF_KEY]) if meta.get(PARENT_REF_KEY) else None,
        needs_review=bool(meta.get(NEEDS_REVIEW_KEY, False)),
        review_reason=str(meta.get(REVIEW_REASON_KEY) or ""),
        withdrawn_reason=str(meta[WITHDRAWN_REASON_KEY]) if meta.get(WITHDRAWN_REASON_KEY) else None,
        withdrawn_at=datetime.fromisoformat(str(meta[WITHDRAWN_AT_KEY])) if meta.get(WITHDRAWN_AT_KEY) else None,
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
        collection_name = f"{settings.chroma_collection_prefix}_{settings.project_id}"
        persist_path = settings.chroma_persist_path.strip()
        self._client: ClientAPI
        self._collection: Collection
        if client is None and persist_path:
            # Every memkernel process opens a persisted store here (#69): the lock serialises a new store's creation.
            with _store_open_lock(persist_path):
                self._client = chromadb.PersistentClient(path=persist_path)
                self._collection = self._open_collection(collection_name)
        else:
            self._client = client if client is not None else chromadb.EphemeralClient()
            self._collection = self._open_collection(collection_name)
        self._lock_dir, self._store_key = self._lock_identity(collection_name, persist_path, client is not None)

    def _lock_identity(self, collection_name: str, persist_path: str, injected: bool) -> tuple[Path | None, str]:
        """The store's own lock identity (store-locks L1): its directory and a key, never a setting.

        A persistent client's locks live in its resolved directory, named by tenant, database and collection. An
        in-memory store's locks are process-wide per tenant, database and collection: separately built
        ``EphemeralClient`` objects share one data set. An injected persistent client must use the configured
        directory when one is configured.
        """
        client_settings = self._client.get_settings()
        tenant = str(getattr(self._client, "tenant", DEFAULT_TENANT))
        database = str(getattr(self._client, "database", DEFAULT_DATABASE))
        digest = hashlib.sha256(f"{tenant}/{database}/{collection_name}".encode()).hexdigest()
        name_key = digest[:_STORE_KEY_HASH_CHARS]
        if not client_settings.is_persistent:
            return None, f"memory:{name_key}"
        directory = Path(os.path.realpath(str(client_settings.persist_directory)))
        if injected and persist_path and directory != Path(os.path.realpath(persist_path)):
            raise ValueError(
                f"the injected client's store {directory} is not the configured MEMKERNEL_CHROMA_PERSIST_PATH "
                f"{persist_path}"
            )
        return directory, f"{directory}:{name_key}"

    @contextmanager
    def exclusive(self, name: str) -> Iterator[None]:
        """Hold the store's lock ``name`` until the block exits (store-locks L2, L4).

        Raises ``ValueError`` for a name outside ``STORE_LOCK_NAMES`` and ``LockReentryError`` when this thread
        already holds the lock. Other threads of this process wait on an in-process lock; other processes wait on
        an ``flock`` file in the store's directory. Without ``fcntl`` the cross-process part runs unlocked, with
        one warning per process and lock name.
        """
        if name not in STORE_LOCK_NAMES:
            raise ValueError(f"unknown store lock {name!r}; expected one of {sorted(STORE_LOCK_NAMES)}")
        pair = (self._store_key, name)
        held = _held_pairs()
        if pair in held:
            raise LockReentryError(
                f"store lock {name!r} is already held by this thread; store locks are not re-entrant"
            )
        lock = _thread_lock(pair)
        _acquire_thread_lock(lock, name, self._store_key)
        held.add(pair)
        try:
            if self._lock_dir is None:
                yield
            elif fcntl is None:
                if name not in _unlocked_warned:
                    _unlocked_warned.add(name)
                    logger.warning("fcntl is not available: store lock %s runs unlocked across processes", name)
                yield
            else:
                digest = self._store_key.rsplit(":", 1)[1]
                path = self._lock_dir / f"{STORE_LOCK_FILE_PREFIX}{name}-{digest}.lock"
                with _file_lock(path, name, self._store_key):
                    yield
        finally:
            held.discard(pair)
            lock.release()

    def _open_collection(self, name: str) -> Collection:
        return self._client.get_or_create_collection(name=name, metadata={"hnsw:space": "cosine"})

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

    def list_all(self, where: dict[str, Any] | None = None, include_content: bool = True) -> list[Memory]:
        """Return all memories, optionally filtered by metadata.

        ``include_content=False`` fetches ids and metadata only; ``content`` is
        then empty, which keeps maintenance passes free of document loads.
        """
        kwargs: dict[str, Any] = {"include": ["metadatas", "documents"] if include_content else ["metadatas"]}
        if where is not None:
            kwargs["where"] = where

        result = self._collection.get(**kwargs)
        ids: list[str] = result.get("ids") or []
        raw_docs = result.get("documents") if include_content else None
        documents: list[str] = list(raw_docs) if raw_docs is not None else [""] * len(ids)
        raw_metas = result.get("metadatas")
        metadatas: list[Mapping[str, Any]] = list(raw_metas) if raw_metas is not None else []

        return [_memory_from_chroma(ids, documents, metadatas, i) for i in range(len(ids))]

    def find_by_hash(self, content_hash: str, memory_type: str, source: str | None = None) -> Memory | None:
        """Find a memory by content hash + type (+ source). Returns the first live non-chunk match or None.

        Code chunk records (``code_chunk: true``) are skipped so that a file
        whose single chunk equals the whole file cannot shadow its canonical;
        superseded and withdrawn records (``superseded_by`` or ``withdrawn_reason`` set) are history, not dedup hits,
        so re-retaining reverted content creates a new live record.
        """
        conditions: list[dict[str, Any]] = [{"hash": content_hash}, {"type": memory_type}]
        if source is not None:
            conditions.append({"source": source})
        result = self._collection.get(where={"$and": conditions}, include=["metadatas", "documents"])
        ids: list[str] = result.get("ids") or []
        raw_docs = result.get("documents")
        documents: list[str] = list(raw_docs) if raw_docs is not None else []
        raw_metas = result.get("metadatas")
        metadatas: list[Mapping[str, Any]] = list(raw_metas) if raw_metas is not None else []

        for index, meta in enumerate(metadatas):
            if meta.get(CODE_CHUNK_KEY) is True or meta.get(SUPERSEDED_BY_KEY) or meta.get(WITHDRAWN_REASON_KEY):
                continue  # chunk records and retired (superseded or withdrawn) records are never dedup hits
            return _memory_from_chroma(ids, documents, metadatas, index)
        return None

    def update_metadata(self, ref_id: str, metadata: dict[str, Any]) -> None:
        """Overwrite only the caller's keys; ChromaDB keeps every other key (store-locks L3).

        Only the caller's keys are sent, so this never writes back a stale value of a key it was not given. A
        ``tags`` key raises ``ValueError``: ``merge_tags`` is the only writer of tags.
        """
        if TAGS_KEY in metadata:
            raise ValueError("update_metadata does not write tags; use merge_tags")
        if not self._collection.get(ids=[ref_id], include=[]).get("ids"):
            return
        self._collection.update(ids=[ref_id], metadatas=[_to_chroma_metadata(metadata)])

    def merge_tags(self, ref_id: str, add: Sequence[str] = (), remove: Sequence[str] = ()) -> bool:
        """Drop ``remove``, then append the missing ``add`` tags, read and written under the tags lock (L3).

        A tag in both ends up present, after the kept ones, so ``remove=<all>`` with ``add=<list>`` sets the tags to
        exactly that list in one locked write. Returns False when the record is unknown or nothing changed.
        """
        with self.exclusive(STORE_LOCK_TAGS):
            current = self._read_tags(ref_id)
            if current is None:
                return False
            dropped = set(remove)
            tags = list(dict.fromkeys([*(tag for tag in current if tag not in dropped), *add]))
            if tags == current:
                return False
            self._collection.update(ids=[ref_id], metadatas=[{TAGS_KEY: ",".join(tags)}])
            return True

    def _read_tags(self, ref_id: str) -> list[str] | None:
        result = self._collection.get(ids=[ref_id], include=["metadatas"])
        metadatas = result.get("metadatas")
        if not result.get("ids") or not metadatas:
            return None
        return _split_csv(metadatas[0].get(TAGS_KEY))

    def count(self, where: dict[str, Any] | None = None) -> int:
        """Return the number of records in the collection, or of those matching ``where``.

        A filtered count fetches ids only — no documents, metadata or embeddings.
        """
        if where is None:
            return self._collection.count()
        result = self._collection.get(where=where, include=[])
        return len(result.get("ids") or [])

    def list_collections(self) -> list[dict[str, Any]]:
        """List all collections accessible via this client with their record counts."""
        return [{"name": coll.name, "count": coll.count()} for coll in self._client.list_collections()]

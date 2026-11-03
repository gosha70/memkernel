# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""Store locks and the single tag writer, in one process (memkernel-0-7-store-locks SC-1, SC-1a, SC-2, SC-3)."""

from __future__ import annotations

import logging
import threading
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast

import chromadb
import pytest

from memkernel.config import MemKernelSettings
from memkernel.core.models import STORE_LOCK_TAGS, STORE_LOCK_WIKI_IMPORT, LockReentryError, MemoryType
from memkernel.core.services import MemoryService
from memkernel.retrieval.search import HybridSearchService
from memkernel.retrieval.sparse import BM25Index
from memkernel.storage import chroma
from memkernel.storage.chroma import STORE_LOCK_FILE_PREFIX, ChromaVectorStore
from tests.conftest import MockEmbedding

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

pytestmark = pytest.mark.unit

_BLOCKED_FOR = 0.3  # how long a second taker must stay blocked while the first holds the lock


def _settings(**overrides: Any) -> MemKernelSettings:
    base: dict[str, Any] = {"project_id": f"locks-{uuid.uuid4().hex[:8]}", "chroma_persist_path": ""}
    base.update(overrides)
    return MemKernelSettings(**cast("Any", base))


def _record(store: ChromaVectorStore, ref_id: str, tags: str = "a,b") -> None:
    metadata = {
        "project_id": "p",
        "session_id": "s",
        "type": MemoryType.FACT,
        "hash": ref_id,
        "token_count": 1,
        "source": "t",
        "timestamp": datetime(2026, 1, 1, tzinfo=UTC),
        "tags": tags,
    }
    store.upsert(ref_id, f"content {ref_id}", [0.6, 0.8], metadata)


@pytest.fixture
def store() -> ChromaVectorStore:
    return ChromaVectorStore(_settings(), client=chromadb.EphemeralClient())


@pytest.fixture
def no_fcntl(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(chroma, "fcntl", None)
    monkeypatch.setattr(chroma, "_unlocked_warned", set())
    yield


def _blocks_until_released(first: ChromaVectorStore, second: ChromaVectorStore, name: str) -> bool:
    """Whether ``second.exclusive(name)`` waits while ``first`` holds it, and gets it once released."""
    holding, release, got = threading.Event(), threading.Event(), threading.Event()

    def hold() -> None:
        with first.exclusive(name):
            holding.set()
            release.wait(5)

    def take() -> None:
        with second.exclusive(name):
            got.set()

    holder = threading.Thread(target=hold)
    holder.start()
    holding.wait(5)
    taker = threading.Thread(target=take)
    taker.start()
    blocked = not got.wait(_BLOCKED_FOR)
    release.set()
    holder.join(5)
    taker.join(5)
    return blocked and got.is_set()


# --- L3: tags have one writer -------------------------------------------------------------------------------------


def test_update_metadata_refuses_tags(store: ChromaVectorStore) -> None:
    _record(store, "r")
    with pytest.raises(ValueError, match="merge_tags"):
        store.update_metadata("r", {"tags": "x"})
    memory = store.get_by_id("r")
    assert memory is not None and memory.tags == ["a", "b"]


def test_update_metadata_keeps_keys_it_is_not_given(store: ChromaVectorStore) -> None:
    _record(store, "r")
    store.update_metadata("r", {"session_id": "new"})
    memory = store.get_by_id("r")
    assert memory is not None and memory.session_id == "new" and memory.tags == ["a", "b"]
    store.update_metadata("unknown", {"session_id": "x"})  # an unknown record is a no-op, as before


def test_chromadb_update_merges_metadata_keys() -> None:
    """Pins the chromadb behavior L3 relies on: ``update`` keeps the keys it is not given."""
    collection = chromadb.EphemeralClient().get_or_create_collection(f"pin-{uuid.uuid4().hex[:8]}")
    collection.add(ids=["x"], documents=["d"], embeddings=[[0.1, 0.2]], metadatas=[{"tags": "t1", "n": 1}])
    collection.update(ids=["x"], metadatas=[{"n": 2}])
    assert collection.get(ids=["x"], include=["metadatas"])["metadatas"] == [{"tags": "t1", "n": 2}]


def test_separate_ephemeral_clients_share_one_data_set() -> None:
    """Pins the chromadb behavior L1's in-memory lock key relies on."""
    name = f"pin-{uuid.uuid4().hex[:8]}"
    chromadb.EphemeralClient().get_or_create_collection(name).add(ids=["x"], documents=["d"], embeddings=[[0.1, 0.2]])
    assert chromadb.EphemeralClient().get_or_create_collection(name).count() == 1


def test_merge_tags_drops_then_appends_and_reports_a_change(store: ChromaVectorStore) -> None:
    _record(store, "r", "a,b,c")
    assert store.merge_tags("r", add=["d", "a"], remove=["b"]) is True
    assert store.get_by_id("r").tags == ["a", "c", "d"]  # type: ignore[union-attr]
    assert store.merge_tags("r", add=["a"]) is False  # nothing changed
    assert store.merge_tags("r", add=["x", "c"], remove=["a", "c", "d"]) is True  # in both: present, after the kept
    assert store.get_by_id("r").tags == ["x", "c"]  # type: ignore[union-attr]
    assert store.merge_tags("unknown", add=["a"]) is False


# --- L2: exclusive, not re-entrant ----------------------------------------------------------------------------------


def test_exclusive_refuses_an_unknown_name(store: ChromaVectorStore) -> None:
    with pytest.raises(ValueError, match="unknown store lock"), store.exclusive("../other"):
        pass


@pytest.mark.parametrize("persisted", [False, True])
def test_a_nested_take_of_the_same_lock_raises_and_the_outer_one_stays_held(
    persisted: bool, tmp_path: Path, request: pytest.FixtureRequest
) -> None:
    settings = _settings(chroma_persist_path=str(tmp_path / "chroma")) if persisted else _settings()
    first = ChromaVectorStore(settings) if persisted else ChromaVectorStore(settings, client=chromadb.EphemeralClient())
    with first.exclusive(STORE_LOCK_WIKI_IMPORT):
        with pytest.raises(LockReentryError, match="not re-entrant"), first.exclusive(STORE_LOCK_WIKI_IMPORT):
            pass
        with first.exclusive(STORE_LOCK_TAGS):  # a different name nests fine
            pass
        other = ChromaVectorStore(_settings(), client=chromadb.EphemeralClient())
        with other.exclusive(STORE_LOCK_WIKI_IMPORT):  # so does another store
            pass
        assert _still_held(first, STORE_LOCK_WIKI_IMPORT)
    with first.exclusive(STORE_LOCK_WIKI_IMPORT):  # released normally
        pass


def _still_held(store: ChromaVectorStore, name: str) -> bool:
    """From another thread, whether ``name`` is taken (the take would block)."""
    got = threading.Event()

    def take() -> None:
        with store.exclusive(name):
            got.set()

    thread = threading.Thread(target=take, daemon=True)
    thread.start()
    blocked = not got.wait(_BLOCKED_FOR)
    return blocked and thread.is_alive()


def test_merge_tags_inside_the_tags_lock_raises(store: ChromaVectorStore) -> None:
    _record(store, "r")
    with store.exclusive(STORE_LOCK_TAGS), pytest.raises(LockReentryError):
        store.merge_tags("r", add=["c"])


def test_a_nested_take_raises_without_fcntl_too(tmp_path: Path, no_fcntl: None) -> None:
    store = ChromaVectorStore(_settings(chroma_persist_path=str(tmp_path / "chroma")))
    with store.exclusive(STORE_LOCK_TAGS), pytest.raises(LockReentryError), store.exclusive(STORE_LOCK_TAGS):
        pass


# --- L1: lock identity is the store's own -------------------------------------------------------------------------


def test_two_adapters_on_one_ephemeral_client_serialize() -> None:
    client = chromadb.EphemeralClient()
    settings = _settings()
    assert _blocks_until_released(
        ChromaVectorStore(settings, client=client), ChromaVectorStore(settings, client=client), STORE_LOCK_WIKI_IMPORT
    )


def test_two_separately_built_ephemeral_clients_serialize() -> None:
    settings = _settings()
    first = ChromaVectorStore(settings, client=chromadb.EphemeralClient())
    second = ChromaVectorStore(settings, client=chromadb.EphemeralClient())
    _record(first, "seen")
    assert second.get_by_id("seen") is not None  # one data set, so one lock
    assert _blocks_until_released(first, second, STORE_LOCK_WIKI_IMPORT)


def test_two_collections_do_not_block_each_other() -> None:
    client = chromadb.EphemeralClient()
    first = ChromaVectorStore(_settings(), client=client)
    second = ChromaVectorStore(_settings(), client=client)
    with first.exclusive(STORE_LOCK_WIKI_IMPORT), second.exclusive(STORE_LOCK_WIKI_IMPORT):
        pass


def test_an_injected_persistent_client_must_use_the_configured_directory(tmp_path: Path) -> None:
    client = chromadb.PersistentClient(path=str(tmp_path / "elsewhere"))
    with pytest.raises(ValueError, match="not the configured MEMKERNEL_CHROMA_PERSIST_PATH"):
        ChromaVectorStore(_settings(chroma_persist_path=str(tmp_path / "configured")), client=client)


def test_an_injected_persistent_client_is_refused_when_the_environment_names_another_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MEMKERNEL_CHROMA_PERSIST_PATH", str(tmp_path / "configured"))
    settings = MemKernelSettings(project_id=f"locks-{uuid.uuid4().hex[:8]}")
    with pytest.raises(ValueError, match="not the configured MEMKERNEL_CHROMA_PERSIST_PATH"):
        ChromaVectorStore(settings, client=chromadb.PersistentClient(path=str(tmp_path / "elsewhere")))


def test_with_the_default_setting_an_injected_persistent_client_is_allowed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("MEMKERNEL_CHROMA_PERSIST_PATH", raising=False)
    settings = MemKernelSettings(project_id=f"locks-{uuid.uuid4().hex[:8]}")
    assert "chroma_persist_path" not in settings.model_fields_set and settings.chroma_persist_path
    directory = tmp_path / "elsewhere"
    store = ChromaVectorStore(settings, client=chromadb.PersistentClient(path=str(directory)))
    with store.exclusive(STORE_LOCK_WIKI_IMPORT):
        pass
    assert list(directory.glob(f"{STORE_LOCK_FILE_PREFIX}{STORE_LOCK_WIKI_IMPORT}-*.lock"))


def test_another_thread_waits_instead_of_raising(store: ChromaVectorStore) -> None:
    """Re-entry is per thread: a second thread of the same process waits for the lock."""
    assert _blocks_until_released(store, store, STORE_LOCK_TAGS)


def test_an_injected_persistent_client_keys_its_locks_by_its_own_directory(tmp_path: Path) -> None:
    directory = tmp_path / "store"
    for configured in ("", str(directory)):
        store = ChromaVectorStore(
            _settings(chroma_persist_path=configured), client=chromadb.PersistentClient(path=str(directory))
        )
        with store.exclusive(STORE_LOCK_WIKI_IMPORT):
            pass
    assert [p.name for p in directory.glob(f"{STORE_LOCK_FILE_PREFIX}{STORE_LOCK_WIKI_IMPORT}-*.lock")]


def test_a_long_wait_is_logged_once(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    monkeypatch.setattr(chroma, "LOCK_WAIT_LOG_SECONDS", 0.05)
    client = chromadb.EphemeralClient()
    settings = _settings()
    with caplog.at_level(logging.INFO, logger=chroma.__name__):
        assert _blocks_until_released(
            ChromaVectorStore(settings, client=client), ChromaVectorStore(settings, client=client), STORE_LOCK_TAGS
        )
    assert sum("waiting for store lock tags" in r.getMessage() for r in caplog.records) == 1


# --- L4: without fcntl --------------------------------------------------------------------------------------------


def test_without_fcntl_locks_run_and_warn_once_per_name(
    tmp_path: Path, no_fcntl: None, caplog: pytest.LogCaptureFixture
) -> None:
    directory = tmp_path / "chroma"
    store = ChromaVectorStore(_settings(chroma_persist_path=str(directory)))
    _record(store, "r")
    with caplog.at_level(logging.WARNING, logger=chroma.__name__):
        for _ in range(3):
            with store.exclusive(STORE_LOCK_WIKI_IMPORT):
                pass
            store.merge_tags("r", add=["c"])
    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 2 and all("runs unlocked" in w for w in warnings)
    assert not list(directory.glob(f"{STORE_LOCK_FILE_PREFIX}*.lock"))
    assert store.get_by_id("r").tags == ["a", "b", "c"]  # type: ignore[union-attr]


def _service(settings: MemKernelSettings) -> MemoryService:
    store = ChromaVectorStore(settings)
    sparse = BM25Index()
    search = HybridSearchService(store, MockEmbedding(), sparse, settings)
    return MemoryService(store, MockEmbedding(), sparse, search, settings)


@pytest.mark.parametrize("fcntl_available", [True, False])
def test_a_dedup_hit_merges_its_tags_through_merge_tags(
    fcntl_available: bool, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if not fcntl_available:
        monkeypatch.setattr(chroma, "fcntl", None)
    svc = _service(_settings(chroma_persist_path=str(tmp_path / "chroma")))
    calls: list[tuple[str, tuple[str, ...]]] = []
    real = ChromaVectorStore.merge_tags

    def spy(self: ChromaVectorStore, ref_id: str, add: Any = (), remove: Any = ()) -> bool:
        calls.append((ref_id, tuple(add)))
        return bool(real(self, ref_id, add, remove))

    monkeypatch.setattr(ChromaVectorStore, "merge_tags", spy)
    ref = svc.retain("pytest needs the project id", MemoryType.FACT, tags=["ci"])
    assert svc.retain("pytest needs the project id", MemoryType.FACT, tags=["env"]) == ref
    memory = svc.get(ref, touch=False)
    assert memory is not None and memory.tags == ["ci", "env"]
    assert calls == [(ref, ("env",))]

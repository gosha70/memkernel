"""Unit tests for tiered-memory behaviour in MemoryService: metadata, touch, promote, consolidate."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import chromadb
import pytest

from memkernel.config import MemKernelSettings
from memkernel.core.models import MemoryTier, MemoryType
from memkernel.core.services import MemoryService
from memkernel.factory import build_service
from memkernel.retrieval.search import HybridSearchService
from memkernel.retrieval.sparse import BM25Index
from memkernel.storage.chroma import ChromaVectorStore
from tests.conftest import MockEmbedding

pytestmark = pytest.mark.unit


def _settings(**overrides: Any) -> MemKernelSettings:
    base: dict[str, Any] = {"project_id": f"tiers-{uuid.uuid4().hex[:8]}", "search_top_k": 5}
    base.update(overrides)
    return MemKernelSettings(**base)


def _service(settings: MemKernelSettings | None = None) -> tuple[MemoryService, ChromaVectorStore]:
    settings = settings or _settings()
    store = ChromaVectorStore(settings, client=chromadb.EphemeralClient())
    sparse = BM25Index()
    search = HybridSearchService(store, MockEmbedding(), sparse, settings)
    return MemoryService(store, MockEmbedding(), sparse, search, settings), store


def _backdate(store: ChromaVectorStore, ref_id: str, days: float) -> None:
    ts = datetime.now(UTC) - timedelta(days=days)
    store.update_metadata(ref_id, {"timestamp": ts.isoformat()})


# --------------------------------------------------------------------------
# metadata
# --------------------------------------------------------------------------


def test_retain_assigns_tier_and_default_importance() -> None:
    svc, _ = _service()
    decision = svc.get(svc.retain("Use Postgres.", MemoryType.DECISION), touch=False)
    episode = svc.get(svc.retain("Ran the tests.", MemoryType.EPISODE), touch=False)
    task = svc.get(svc.retain("Current goal: wire the API.", MemoryType.TASK), touch=False)
    assert decision is not None and decision.tier == MemoryTier.LONG_TERM and decision.importance == 0.9
    assert episode is not None and episode.tier == MemoryTier.SHORT_TERM and episode.importance == 0.4
    assert task is not None and task.tier == MemoryTier.WORKING


def test_retain_stores_importance_tags_and_supersedes() -> None:
    svc, _ = _service()
    old = svc.retain("Use SQLite.", MemoryType.DECISION)
    new = svc.retain("Use Postgres.", MemoryType.DECISION, importance=1.0, tags=["db", "infra"], supersedes=old)
    memory = svc.get(new, touch=False)
    assert memory is not None
    assert memory.importance == 1.0
    assert memory.tags == ["db", "infra"]
    assert memory.supersedes == old


def test_retain_dedup_merges_tags_and_raises_importance() -> None:
    svc, _ = _service()
    first = svc.retain("Use ruff.", MemoryType.CONVENTION, importance=0.5, tags=["lint"])
    second = svc.retain("Use ruff.", MemoryType.CONVENTION, importance=0.8, tags=["style"])
    assert first == second
    memory = svc.get(first, touch=False)
    assert memory is not None
    assert memory.importance == 0.8
    assert memory.tags == ["lint", "style"]


def test_legacy_records_without_tier_metadata_still_load() -> None:
    svc, store = _service()
    ref_id = svc.retain("legacy", MemoryType.EPISODE)
    # Simulate a 0.1.x record: strip the new keys from the stored metadata.
    raw = store._collection.get(ids=[ref_id], include=["metadatas"])  # noqa: SLF001
    meta = dict(raw["metadatas"][0])  # type: ignore[index]
    for key in ("tier", "importance", "access_count", "tags"):
        meta.pop(key, None)
    store._collection.update(ids=[ref_id], metadatas=[meta])  # noqa: SLF001
    memory = store.get_by_id(ref_id)
    assert memory is not None
    assert memory.tier == MemoryTier.SHORT_TERM
    assert memory.importance == 0.4
    assert memory.access_count == 0


# --------------------------------------------------------------------------
# access tracking
# --------------------------------------------------------------------------


def test_recall_and_get_record_access() -> None:
    svc, _ = _service()
    ref_id = svc.retain("The build uses poetry.", MemoryType.FACT)
    assert svc.recall("poetry build")[0].ref_id == ref_id
    memory = svc.get(ref_id)
    assert memory is not None
    assert memory.access_count == 1  # recall touched it; get() reads the pre-touch state
    after = svc.get(ref_id, touch=False)
    assert after is not None
    assert after.access_count == 2
    assert after.last_accessed is not None


def test_recall_touch_false_does_not_record_access() -> None:
    svc, _ = _service()
    ref_id = svc.retain("quiet", MemoryType.FACT)
    svc.recall("quiet", touch=False)
    memory = svc.get(ref_id, touch=False)
    assert memory is not None and memory.access_count == 0


def test_recalled_episode_survives_past_base_ttl() -> None:
    svc, store = _service(_settings(episode_ttl_days=30, access_boost=1.0))
    ref_id = svc.retain("Deployed v1 to staging.", MemoryType.EPISODE)
    svc.recall("staging deploy")  # access_count -> 1, TTL doubles to 60 days
    _backdate(store, ref_id, days=45)
    store.update_metadata(ref_id, {"last_accessed": (datetime.now(UTC) - timedelta(days=45)).isoformat()})
    assert [r.ref_id for r in svc.recall("staging deploy", touch=False)] == [ref_id]


def test_untouched_expired_episode_is_hidden() -> None:
    svc, store = _service(_settings(episode_ttl_days=30))
    ref_id = svc.retain("Old news.", MemoryType.EPISODE)
    _backdate(store, ref_id, days=45)
    assert svc.recall("old news", touch=False) == []


# --------------------------------------------------------------------------
# tier filter, supersedes, ranking
# --------------------------------------------------------------------------


def test_recall_tier_filter() -> None:
    svc, _ = _service()
    svc.retain("alpha convention", MemoryType.CONVENTION)
    ep = svc.retain("alpha episode", MemoryType.EPISODE)
    results = svc.recall("alpha", tier=MemoryTier.SHORT_TERM, touch=False)
    assert [r.ref_id for r in results] == [ep]
    assert all(r.tier == MemoryTier.SHORT_TERM for r in results)


def test_superseded_memory_is_hidden_from_recall() -> None:
    svc, _ = _service()
    old = svc.retain("Database: SQLite.", MemoryType.DECISION)
    new = svc.retain("Database: Postgres.", MemoryType.DECISION, supersedes=old)
    ids = [r.ref_id for r in svc.recall("database", touch=False)]
    assert new in ids
    assert old not in ids


def test_importance_breaks_ties_in_ranking() -> None:
    svc, _ = _service(_settings(recall_weight_recency=0.0, recall_weight_importance=1.0))
    low = svc.retain("zeta note one", MemoryType.OBSERVATION, importance=0.1)
    high = svc.retain("zeta note two", MemoryType.OBSERVATION, importance=0.9)
    ids = [r.ref_id for r in svc.recall("zeta note", touch=False)]
    assert ids.index(high) < ids.index(low)


# --------------------------------------------------------------------------
# promote / consolidate / forget_expired
# --------------------------------------------------------------------------


def test_promote_creates_long_term_memory_with_provenance() -> None:
    svc, _ = _service()
    episode = svc.retain("We tried Celery; it fought the async stack.", MemoryType.EPISODE, tags=["queue"])
    new_ref = svc.promote(episode, MemoryType.DECISION, content="Do not use Celery; use arq.", tags=["async"])
    assert new_ref is not None and new_ref != episode
    memory = svc.get(new_ref, touch=False)
    assert memory is not None
    assert memory.type == MemoryType.DECISION
    assert memory.tier == MemoryTier.LONG_TERM
    assert memory.promoted_from == episode
    assert memory.tags == ["queue", "async"]
    assert memory.content == "Do not use Celery; use arq."


def test_promote_missing_returns_none() -> None:
    svc, _ = _service()
    assert svc.promote("nope", MemoryType.FACT) is None


def test_consolidate_ranks_candidates_and_skips_promoted() -> None:
    svc, _ = _service()
    quiet = svc.retain("quiet observation", MemoryType.OBSERVATION)
    hot = svc.retain("hot observation", MemoryType.OBSERVATION)
    done = svc.retain("already promoted", MemoryType.EPISODE)
    svc.retain("a decision", MemoryType.DECISION)
    svc.retain("checkpoint", MemoryType.EPISODE, checkpoint=True)
    for _ in range(3):
        svc.get(hot)
    svc.promote(done, MemoryType.FACT)
    report = svc.consolidate()
    ids = [c["ref_id"] for c in report["candidates"]]
    assert ids[0] == hot
    assert quiet in ids
    assert done not in ids
    assert all(c["tier"] != MemoryTier.LONG_TERM.value for c in report["candidates"])
    assert report["purged"] == 0


def test_consolidate_purges_expired_and_filters_by_session() -> None:
    svc, store = _service(_settings(observation_ttl_days=7))
    stale = svc.retain("stale", MemoryType.OBSERVATION, session_id="s1")
    _backdate(store, stale, days=10)
    s1 = svc.retain("fresh s1", MemoryType.OBSERVATION, session_id="s1")
    svc.retain("fresh s2", MemoryType.OBSERVATION, session_id="s2")
    report = svc.consolidate(session_id="s1")
    assert report["purged"] == 1
    assert [c["ref_id"] for c in report["candidates"]] == [s1]
    assert svc.get(stale, touch=False) is None


def test_forget_expired_never_touches_long_term() -> None:
    svc, store = _service(_settings(episode_ttl_days=1))
    keep = svc.retain("ancient decision", MemoryType.DECISION)
    drop = svc.retain("ancient episode", MemoryType.EPISODE)
    _backdate(store, keep, days=1000)
    _backdate(store, drop, days=1000)
    assert svc.forget_expired() == 1
    assert svc.get(keep, touch=False) is not None
    assert svc.get(drop, touch=False) is None


def test_stats_reports_by_tier() -> None:
    svc, _ = _service()
    svc.retain("d", MemoryType.DECISION)
    svc.retain("e", MemoryType.EPISODE)
    svc.retain("t", MemoryType.TASK)
    by_tier = svc.stats()["by_tier"]
    assert by_tier == {"long_term": 1, "short_term": 1, "working": 1}


def test_factory_builds_working_service() -> None:
    settings = _settings(chroma_persist_path="")
    svc = build_service(settings=settings, embedding=MockEmbedding(), chroma_client=chromadb.EphemeralClient())
    ref_id = svc.retain("factory works", MemoryType.FACT)
    assert svc.recall("factory", touch=False)[0].ref_id == ref_id

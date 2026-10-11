"""Unit tests for tiered lifecycle: decay, reinforcement, recency scoring."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from memkernel.config import MemKernelSettings
from memkernel.core.models import DEFAULT_IMPORTANCE, TYPE_TIER, MemoryTier, MemoryType, tier_of
from memkernel.memory.lifecycle import effective_ttl_days, is_expired, recency_score
from memkernel.memory.types import get_half_life_days, get_ttl_days

pytestmark = pytest.mark.unit


def _settings(**overrides: object) -> MemKernelSettings:
    return MemKernelSettings(project_id="lifecycle-test", **overrides)  # type: ignore[arg-type]


def test_every_type_has_a_tier_and_importance() -> None:
    for memory_type in MemoryType:
        assert memory_type in TYPE_TIER
        assert memory_type in DEFAULT_IMPORTANCE
        assert 0.0 <= DEFAULT_IMPORTANCE[memory_type] <= 1.0


def test_long_term_types_never_expire() -> None:
    settings = _settings()
    old = datetime.now(UTC) - timedelta(days=10_000)
    for memory_type in MemoryType:
        if tier_of(memory_type) == MemoryTier.LONG_TERM:
            assert get_ttl_days(memory_type, settings) is None
            assert not is_expired(memory_type, old, settings)


def test_short_term_and_working_have_base_ttl() -> None:
    settings = _settings(episode_ttl_days=30, observation_ttl_days=7, task_ttl_hours=24)
    assert get_ttl_days(MemoryType.EPISODE, settings) == 30
    assert get_ttl_days(MemoryType.OBSERVATION, settings) == 7
    assert get_ttl_days(MemoryType.TASK, settings) == pytest.approx(1.0)


def test_episode_expires_after_ttl() -> None:
    settings = _settings(episode_ttl_days=30)
    assert not is_expired(MemoryType.EPISODE, datetime.now(UTC) - timedelta(days=29), settings)
    assert is_expired(MemoryType.EPISODE, datetime.now(UTC) - timedelta(days=31), settings)


def test_task_expires_in_hours() -> None:
    settings = _settings(task_ttl_hours=24)
    assert not is_expired(MemoryType.TASK, datetime.now(UTC) - timedelta(hours=23), settings)
    assert is_expired(MemoryType.TASK, datetime.now(UTC) - timedelta(hours=25), settings)


def test_access_reinforcement_extends_ttl() -> None:
    settings = _settings(episode_ttl_days=30, access_boost=0.5)
    assert effective_ttl_days(MemoryType.EPISODE, 0, settings) == 30
    assert effective_ttl_days(MemoryType.EPISODE, 2, settings) == 60
    # 40 days old: expired without accesses, alive with two recalls
    ts = datetime.now(UTC) - timedelta(days=40)
    assert is_expired(MemoryType.EPISODE, ts, settings, access_count=0)
    assert not is_expired(MemoryType.EPISODE, ts, settings, access_count=2)


def test_last_accessed_resets_the_clock() -> None:
    settings = _settings(episode_ttl_days=30)
    created = datetime.now(UTC) - timedelta(days=45)
    recent = datetime.now(UTC) - timedelta(days=1)
    assert is_expired(MemoryType.EPISODE, created, settings)
    assert not is_expired(MemoryType.EPISODE, created, settings, last_accessed=recent)


def test_recency_score_long_term_is_flat() -> None:
    settings = _settings()
    assert get_half_life_days(MemoryType.DECISION, settings) is None
    old = datetime.now(UTC) - timedelta(days=365)
    assert recency_score(MemoryType.DECISION, old, settings) == 1.0


def test_recency_score_halves_at_half_life() -> None:
    settings = _settings(recency_half_life_days=7.0)
    now = datetime.now(UTC)
    fresh = recency_score(MemoryType.EPISODE, now, settings, now=now)
    week = recency_score(MemoryType.EPISODE, now - timedelta(days=7), settings, now=now)
    assert fresh == pytest.approx(1.0)
    assert week == pytest.approx(0.5, rel=1e-3)


def test_recency_score_uses_last_accessed() -> None:
    settings = _settings(recency_half_life_days=7.0)
    now = datetime.now(UTC)
    stale = now - timedelta(days=70)
    without = recency_score(MemoryType.EPISODE, stale, settings, now=now)
    with_access = recency_score(MemoryType.EPISODE, stale, settings, last_accessed=now, now=now)
    assert without < 0.01
    assert with_access == pytest.approx(1.0)

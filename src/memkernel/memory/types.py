# Copyright (c) EGOGE - All Rights Reserved.
# This software may be used and distributed according to the terms of the MIT license.
"""TTL and decay policies for each MemoryType / MemoryTier."""

from __future__ import annotations

from typing import TYPE_CHECKING

from memkernel.core.models import MemoryTier, MemoryType, tier_of

if TYPE_CHECKING:
    from memkernel.config import MemKernelSettings


def get_ttl_days(memory_type: MemoryType, settings: MemKernelSettings) -> float | None:
    """Return the base TTL in days for a given MemoryType, or None for no expiry.

    Long-term types never expire. Short-term and working types read their
    base TTL from settings so it is configurable at runtime.
    """
    tier = tier_of(memory_type)
    if tier == MemoryTier.LONG_TERM:
        return None
    if memory_type == MemoryType.EPISODE:
        return float(settings.episode_ttl_days)
    if memory_type == MemoryType.OBSERVATION:
        return float(settings.observation_ttl_days)
    if memory_type == MemoryType.TASK:
        return settings.task_ttl_hours / 24.0
    return None  # pragma: no cover — every non-long-term type is handled above


def get_half_life_days(memory_type: MemoryType, settings: MemKernelSettings) -> float | None:
    """Return the recency half-life (days) used for recall scoring, or None for no recency decay."""
    tier = tier_of(memory_type)
    if tier == MemoryTier.WORKING:
        return settings.task_ttl_hours / 24.0 / 2.0
    if tier == MemoryTier.SHORT_TERM:
        return float(settings.recency_half_life_days)
    return None

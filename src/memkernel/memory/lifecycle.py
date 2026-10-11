# Copyright (c) EGOGE - All Rights Reserved.
# This software may be used and distributed according to the terms of the MIT license.
"""Memory lifecycle helpers — decay, retention and expiry.

Forgetting follows an Ebbinghaus-style model (as used by MemoryBank, Zhong et
al. 2023): a memory's retention window grows with every recall, so knowledge
that keeps being useful survives while untouched episodic noise fades.

    effective_ttl = base_ttl * (1 + access_boost * access_count)

Long-term memories never expire; they are curated by consolidation instead.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from memkernel.memory.types import get_half_life_days, get_ttl_days

if TYPE_CHECKING:
    from memkernel.config import MemKernelSettings
    from memkernel.core.models import Memory, MemoryType


def effective_ttl_days(
    memory_type: MemoryType,
    access_count: int,
    settings: MemKernelSettings,
) -> float | None:
    """Return the retention window in days after access-based reinforcement, or None for no expiry."""
    base = get_ttl_days(memory_type, settings)
    if base is None:
        return None
    return base * (1.0 + settings.access_boost * max(0, access_count))


def is_expired(
    memory_type: MemoryType,
    timestamp: datetime,
    settings: MemKernelSettings,
    access_count: int = 0,
    last_accessed: datetime | None = None,
) -> bool:
    """Return True if the memory has exceeded its (reinforced) retention window.

    The clock starts at the later of ``timestamp`` and ``last_accessed`` so a
    recall refreshes the memory the way rehearsal does.
    """
    ttl_days = effective_ttl_days(memory_type, access_count, settings)
    if ttl_days is None:
        return False
    anchor = timestamp
    if last_accessed is not None and last_accessed > anchor:
        anchor = last_accessed
    age_days = (datetime.now(UTC) - anchor).total_seconds() / 86400.0
    return age_days > ttl_days


def memory_is_expired(memory: Memory, settings: MemKernelSettings) -> bool:
    """Convenience wrapper over :func:`is_expired` for a full Memory record."""
    return is_expired(
        memory.type,
        memory.timestamp,
        settings,
        access_count=memory.access_count,
        last_accessed=memory.last_accessed,
    )


def recency_score(
    memory_type: MemoryType,
    timestamp: datetime,
    settings: MemKernelSettings,
    last_accessed: datetime | None = None,
    now: datetime | None = None,
) -> float:
    """Return a recency factor in (0, 1]: exponential decay with a per-tier half-life.

    Long-term memories have no recency decay (always 1.0) — a convention that
    was set two years ago is as relevant as one set yesterday.
    """
    half_life = get_half_life_days(memory_type, settings)
    if half_life is None or half_life <= 0:
        return 1.0
    anchor = timestamp
    if last_accessed is not None and last_accessed > anchor:
        anchor = last_accessed
    current = now or datetime.now(UTC)
    age_days = max(0.0, (current - anchor).total_seconds() / 86400.0)
    return math.exp(-math.log(2.0) * age_days / half_life)

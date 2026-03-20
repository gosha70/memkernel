# Copyright (c) EGOGE - All Rights Reserved.
# This software may be used and distributed according to the terms of the MIT license.
"""Memory lifecycle helpers — TTL enforcement."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from memkernel.memory.types import get_ttl_days

if TYPE_CHECKING:
    from memkernel.config import MemKernelSettings
    from memkernel.core.models import MemoryType


def is_expired(
    memory_type: MemoryType,
    timestamp: datetime,
    settings: MemKernelSettings,
) -> bool:
    """Return True if the memory has exceeded its TTL.

    Memories with no TTL policy (decision, convention, code) never expire.
    Episode memories expire after settings.episode_ttl_days days.
    """
    ttl_days = get_ttl_days(memory_type, settings)
    if ttl_days is None:
        return False
    age = datetime.now(UTC) - timestamp
    return age.days > ttl_days

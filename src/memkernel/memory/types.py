# Copyright (c) EGOGE - All Rights Reserved.
# This software may be used and distributed according to the terms of the MIT license.
"""TTL policies for each MemoryType."""

from __future__ import annotations

from typing import TYPE_CHECKING

from memkernel.core.models import MemoryType

if TYPE_CHECKING:
    from memkernel.config import MemKernelSettings

# None means no expiry.
TTL_POLICIES: dict[MemoryType, int | None] = {
    MemoryType.DECISION: None,
    MemoryType.CONVENTION: None,
    MemoryType.CODE: None,
    MemoryType.EPISODE: 30,  # default; actual value comes from settings
}


def get_ttl_days(memory_type: MemoryType, settings: MemKernelSettings) -> int | None:
    """Return the TTL in days for a given MemoryType.

    EPISODE TTL is read from settings so it is configurable at runtime.
    All other types return None (no expiry).
    """
    if memory_type == MemoryType.EPISODE:
        return settings.episode_ttl_days
    return TTL_POLICIES.get(memory_type)

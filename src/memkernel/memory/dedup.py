# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""Content-hash deduplication helpers."""

from __future__ import annotations

import hashlib


def compute_content_hash(content: str) -> str:
    """Return the SHA-256 hex digest of the UTF-8 encoded content string."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()

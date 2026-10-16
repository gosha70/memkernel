# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""The recorded decision."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

CODE = r"""

def delay(attempt):
    return min(0.25 * 2 ** attempt, 8.0)
"""


def apply(workdir: Path) -> None:
    target = workdir / "backoff.py"
    target.write_text(target.read_text(encoding="utf-8") + CODE if target.exists() else CODE, encoding="utf-8")

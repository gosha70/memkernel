# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""Doubling from one second, no cap."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

CODE = r"""

def delay(attempt):
    return float(2 ** attempt)
"""


def apply(workdir: Path) -> None:
    target = workdir / "backoff.py"
    target.write_text(target.read_text(encoding="utf-8") + CODE if target.exists() else CODE, encoding="utf-8")

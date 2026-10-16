# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""Decimal, zero-padded: the obvious guess."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

CODE = r"""

def order_id(n):
    return str(n).zfill(8)
"""


def apply(workdir: Path) -> None:
    target = workdir / "orders.py"
    target.write_text(target.read_text(encoding="utf-8") + CODE if target.exists() else CODE, encoding="utf-8")

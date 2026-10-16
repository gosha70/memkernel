# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""Base 36, uppercase, padded to 8."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

CODE = r"""

def order_id(n):
    digits = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    out = ""
    while True:
        n, r = divmod(n, 36)
        out = digits[r] + out
        if n == 0:
            break
    return out.rjust(8, "0")
"""


def apply(workdir: Path) -> None:
    target = workdir / "orders.py"
    target.write_text(target.read_text(encoding="utf-8") + CODE if target.exists() else CODE, encoding="utf-8")

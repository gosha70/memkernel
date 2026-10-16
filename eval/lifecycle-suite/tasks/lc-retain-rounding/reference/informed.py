# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""Uses the rule from the first session: half-up."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

CODE = r"""

def total(prices):
    from decimal import ROUND_HALF_UP, Decimal

    s = sum(Decimal(p) for p in prices)
    return str(s.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
"""


def apply(workdir: Path) -> None:
    target = workdir / "billing.py"
    target.write_text(target.read_text(encoding="utf-8") + CODE if target.exists() else CODE, encoding="utf-8")

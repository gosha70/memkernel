# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""The natural default: ISO 4217 exponents."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

CODE = r"""

def to_minor(amount, currency):
    from decimal import Decimal

    exponent = {"JPY": 0, "BHD": 3}.get(currency, 2)
    return int(Decimal(amount) * 10 ** exponent)
"""


def apply(workdir: Path) -> None:
    target = workdir / "money.py"
    target.write_text(target.read_text(encoding="utf-8") + CODE if target.exists() else CODE, encoding="utf-8")

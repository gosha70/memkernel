# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""Current helper with its default mode."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

CODE = r"""from decimal import Decimal

from amounts import quantize


def invoice_total(prices):
    return str(quantize(sum(Decimal(p) for p in prices)))
"""


def apply(workdir: Path) -> None:
    target = workdir / "invoice.py"
    target.write_text(target.read_text(encoding="utf-8") + CODE if target.exists() else CODE, encoding="utf-8")

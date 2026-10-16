# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""The helper that the repository change removed."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

CODE = r"""from decimal import Decimal

from money import to_cents


def invoice_total(prices):
    return f"{to_cents(sum(Decimal(p) for p in prices)) / 100:.2f}"
"""


def apply(workdir: Path) -> None:
    target = workdir / "invoice.py"
    target.write_text(target.read_text(encoding="utf-8") + CODE if target.exists() else CODE, encoding="utf-8")

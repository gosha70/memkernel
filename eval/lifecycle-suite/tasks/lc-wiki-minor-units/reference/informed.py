# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""The recorded decision."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

CODE = r"""

def to_minor(amount, currency):
    from decimal import Decimal

    return int(Decimal(amount) * 10**4)
"""


def apply(workdir: Path) -> None:
    target = workdir / "money.py"
    target.write_text(target.read_text(encoding="utf-8") + CODE if target.exists() else CODE, encoding="utf-8")

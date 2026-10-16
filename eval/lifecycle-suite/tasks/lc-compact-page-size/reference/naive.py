# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""A common page size of 50."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

CODE = r"""

def page_count(total):
    return -(-total // 50)
"""


def apply(workdir: Path) -> None:
    target = workdir / "pages.py"
    target.write_text(target.read_text(encoding="utf-8") + CODE if target.exists() else CODE, encoding="utf-8")

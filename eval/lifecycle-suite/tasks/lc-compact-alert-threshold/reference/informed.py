# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""The remembered rule."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

CODE = r"""

def should_alert(errors, requests):
    return requests >= 400 and errors * 1000 >= requests * 25
"""


def apply(workdir: Path) -> None:
    target = workdir / "alerts.py"
    target.write_text(target.read_text(encoding="utf-8") + CODE if target.exists() else CODE, encoding="utf-8")

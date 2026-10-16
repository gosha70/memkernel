# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""A common 5 percent rule."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

CODE = r"""

def should_alert(errors, requests):
    return requests > 0 and errors / requests > 0.05
"""


def apply(workdir: Path) -> None:
    target = workdir / "alerts.py"
    target.write_text(target.read_text(encoding="utf-8") + CODE if target.exists() else CODE, encoding="utf-8")

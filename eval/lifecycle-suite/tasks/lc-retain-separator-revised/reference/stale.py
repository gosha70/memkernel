# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""The superseded separator."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

CODE = r"""

def to_line(fields):
    return ";".join(fields)
"""


def apply(workdir: Path) -> None:
    target = workdir / "export.py"
    target.write_text(target.read_text(encoding="utf-8") + CODE if target.exists() else CODE, encoding="utf-8")

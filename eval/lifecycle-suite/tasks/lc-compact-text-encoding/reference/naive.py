# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""UTF-8."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

CODE = r"""

def save(path, text):
    from pathlib import Path

    Path(path).write_text(text, encoding="utf-8")
"""


def apply(workdir: Path) -> None:
    target = workdir / "textio.py"
    target.write_text(target.read_text(encoding="utf-8") + CODE if target.exists() else CODE, encoding="utf-8")

# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""No length limit."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

CODE = r"""

def slugify(title):
    import re

    return "-".join(re.findall(r"[a-z0-9]+", title.lower()))
"""


def apply(workdir: Path) -> None:
    target = workdir / "slugs.py"
    target.write_text(target.read_text(encoding="utf-8") + CODE if target.exists() else CODE, encoding="utf-8")

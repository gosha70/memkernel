# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""The natural default: semver tags."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

CODE = r"""

def tag(major, minor, patch, rc=None):
    base = f"v{major}.{minor}.{patch}"
    return base + (f"-rc.{rc}" if rc else "")
"""


def apply(workdir: Path) -> None:
    target = workdir / "tags.py"
    target.write_text(target.read_text(encoding="utf-8") + CODE if target.exists() else CODE, encoding="utf-8")

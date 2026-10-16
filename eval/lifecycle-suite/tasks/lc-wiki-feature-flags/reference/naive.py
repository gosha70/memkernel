# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""Reads the bare name."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

CODE = r"""

def enabled(name, env):
    return env.get(name, "").lower() in ("1", "true", "yes", "on")
"""


def apply(workdir: Path) -> None:
    target = workdir / "flags.py"
    target.write_text(target.read_text(encoding="utf-8") + CODE if target.exists() else CODE, encoding="utf-8")

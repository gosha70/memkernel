# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""The helper that the change removed."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

CODE = r"""from paths import ROOT


def manifest_entry(path):
    return './' + path.relative_to(ROOT).as_posix()
"""


def apply(workdir: Path) -> None:
    target = workdir / "manifest.py"
    target.write_text(target.read_text(encoding="utf-8") + CODE if target.exists() else CODE, encoding="utf-8")

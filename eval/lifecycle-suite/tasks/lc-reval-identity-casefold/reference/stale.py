# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""The attribute that the change renamed."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

CODE = r"""def same_user(a, b):
    return a.uid.casefold() == b.uid.casefold()
"""


def apply(workdir: Path) -> None:
    target = workdir / "identity.py"
    target.write_text(target.read_text(encoding="utf-8") + CODE if target.exists() else CODE, encoding="utf-8")

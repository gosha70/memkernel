# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""The project format."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

CODE = r"""

def stamp(epoch_seconds):
    import datetime

    t = datetime.datetime.fromtimestamp(int(epoch_seconds), datetime.timezone.utc)
    return t.strftime("%Y-%m-%d %H:%M:%S UTC")
"""


def apply(workdir: Path) -> None:
    target = workdir / "events.py"
    target.write_text(target.read_text(encoding="utf-8") + CODE if target.exists() else CODE, encoding="utf-8")

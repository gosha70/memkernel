# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""The revised limit."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

CODE = r"""

def with_retries(call):
    for attempt in range(4):
        try:
            return call()
        except Exception:
            if attempt == 3:
                raise
"""


def apply(workdir: Path) -> None:
    target = workdir / "client.py"
    target.write_text(target.read_text(encoding="utf-8") + CODE if target.exists() else CODE, encoding="utf-8")

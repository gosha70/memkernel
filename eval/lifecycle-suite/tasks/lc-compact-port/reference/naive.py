# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""Default HTTPS port."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

CODE = r"""

def base_url(host):
    return f"https://{host}/"
"""


def apply(workdir: Path) -> None:
    target = workdir / "urls.py"
    target.write_text(target.read_text(encoding="utf-8") + CODE if target.exists() else CODE, encoding="utf-8")

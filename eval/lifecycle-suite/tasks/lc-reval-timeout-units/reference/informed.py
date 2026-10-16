# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""Current API, milliseconds."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

CODE = r"""from config import Config


def timeout_seconds():
    return float(Config.value("request_timeout")) / 1000
"""


def apply(workdir: Path) -> None:
    target = workdir / "net.py"
    target.write_text(target.read_text(encoding="utf-8") + CODE if target.exists() else CODE, encoding="utf-8")

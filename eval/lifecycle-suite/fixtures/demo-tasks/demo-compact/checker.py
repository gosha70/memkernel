# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""Demo checker: the evaluation session wrote ANSWER.txt."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


def check(workdir: Path, oracle_dir: Path) -> tuple[bool, str]:
    answer = workdir / "ANSWER.txt"
    return (answer.is_file(), "ANSWER.txt written" if answer.is_file() else "ANSWER.txt missing")

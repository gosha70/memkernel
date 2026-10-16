# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""Grade the workspace with the hidden oracle driver (outside the sandbox)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from checker_support import run_driver

if TYPE_CHECKING:
    from pathlib import Path


def check(workdir: Path, oracle_dir: Path) -> tuple[bool, str]:
    return run_driver(workdir, oracle_dir)

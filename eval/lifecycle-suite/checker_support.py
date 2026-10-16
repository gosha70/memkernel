# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""Helpers for lifecycle task checkers (harness-free, stdlib-only).

A checker module defines ``check(workdir: Path, oracle_dir: Path) -> tuple[bool, str]``
in the same shape as agent-memory-bench's checkers. ``run_bounded`` replaces
the benchmark's ``harness.checker_run.run_bounded`` so no task imports the
benchmark.
"""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path


def run_bounded(cmd: Sequence[str], *, cwd: Path, timeout_s: float = 60.0) -> subprocess.CompletedProcess[str]:
    """Run ``cmd`` in ``cwd`` with a hard timeout; a timeout returns exit code 124 instead of raising."""
    try:
        return subprocess.run(list(cmd), cwd=cwd, capture_output=True, text=True, timeout=timeout_s, check=False)
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout if isinstance(exc.stdout, str) else ""
        err = exc.stderr if isinstance(exc.stderr, str) else ""
        return subprocess.CompletedProcess(list(cmd), 124, out, err + "\n[timeout]")

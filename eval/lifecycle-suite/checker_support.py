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


RESULT_PATH_ENV = "LC_ORACLE_RESULT"
RESULT_NONCE_ENV = "LC_ORACLE_NONCE"
STARTED = "started"


class CheckerInfrastructureError(RuntimeError):
    """The oracle itself could not run; the trial is invalid (checker_crashed), not an agent failure."""


def _links_outside(workdir: Path) -> list[str]:
    """Symlinks in ``workdir`` that resolve outside it (they would expose host files to grading)."""
    root = workdir.resolve()
    escaping = []
    for path in workdir.rglob("*"):
        if path.is_symlink():
            target = path.resolve()
            if target != root and root not in target.parents:
                escaping.append(path.relative_to(workdir).as_posix())
    return sorted(escaping)


def run_driver(workdir: Path, oracle_dir: Path, timeout_s: float = 60.0) -> tuple[bool, str]:
    """Run ``oracle_dir/driver.py`` against a copy of ``workdir`` and read its verdict from a result file.

    The verdict is never read from stdout, which the candidate's code shares.
    The driver receives a result path and a nonce through its environment,
    removes both before it imports the candidate, writes ``started`` before
    the import and the verdict after grading. No ``started`` record means the
    oracle never ran (raises CheckerInfrastructureError); ``started`` without a
    verdict means the candidate's code ended the process or hung, which is the
    candidate's failure; more than one verdict means something other than the
    oracle wrote to the file, which also fails.

    This channel stops output forging by ordinary agent code. It is not
    tamper-proof: the values stay reachable inside the driver's process (as
    module globals, and on Linux through /proc/self/environ). Candidate code
    runs with a minimal environment (no operator credentials, ``HOME`` and
    ``TMPDIR`` inside a temporary directory) and a workspace that may not link
    outside itself, but it is not otherwise sandboxed.
    """
    import json
    import secrets
    import shutil
    import sys
    import tempfile
    from pathlib import Path as _Path

    driver = oracle_dir / "driver.py"
    if not driver.is_file():
        raise CheckerInfrastructureError(f"oracle driver missing: {driver}")
    escaping = _links_outside(workdir)
    if escaping:
        return False, f"workspace links outside itself: {', '.join(escaping)}"
    nonce = secrets.token_hex(16)
    with tempfile.TemporaryDirectory() as temp:
        stage = _Path(temp) / "work"
        home = _Path(temp) / "home"
        home.mkdir()
        result = _Path(temp) / "result.jsonl"
        shutil.copytree(workdir, stage, symlinks=True, ignore=shutil.ignore_patterns(".git", "__pycache__"))
        env = {key: value for key, value in _base_env().items()}
        env.update({"HOME": str(home), "TMPDIR": temp, RESULT_PATH_ENV: str(result), RESULT_NONCE_ENV: nonce})
        try:
            completed = subprocess.run(
                [sys.executable, str(driver), str(stage)],
                cwd=stage,
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout_s,
                check=False,
            )
            exit_code: int | None = completed.returncode
        except subprocess.TimeoutExpired:
            exit_code = None
        records = []
        if result.exists():
            for line in result.read_text(encoding="utf-8").splitlines():
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if record.get("nonce") == nonce:
                    records.append(record)
    if not any(r.get("status") == STARTED for r in records):
        raise CheckerInfrastructureError(f"oracle did not start (exit {exit_code})")
    verdicts = [r for r in records if "verdict" in r]
    if exit_code is None:
        return False, "candidate code did not finish within the checker's time limit"
    if not verdicts:
        return False, f"candidate code ended the grading process (exit {exit_code})"
    if len(verdicts) > 1:
        return False, "more than one verdict was written; the result file was tampered with"
    verdict = str(verdicts[0]["verdict"])
    return verdict == "OK", verdict


def _base_env() -> dict[str, str]:
    """The only parent variables grading passes on: none of them can carry a credential."""
    import os

    return {key: os.environ[key] for key in ("PATH", "LANG", "LC_ALL") if key in os.environ}

# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""The calibration entry point's exit-status and secret-scan contract (eval/lifecycle-suite/calibration/run.sh).

The real script runs under bash with stub ``curl``, ``claude``, ``wiki-studio``,
runner and scanner, so ``preflight`` is exercised as written and nothing is
bypassed: the stub ``curl`` answers like the Models API with a workspace header.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tests.unit._lifecycle_suite import SUITE_DIR

pytestmark = [
    pytest.mark.unit,
    pytest.mark.skipif(shutil.which("bash") is None, reason="run.sh is a bash script"),
]

RUN_SH = SUITE_DIR / "calibration" / "run.sh"
WORKSPACE = "wrkspc_test"


def _executable(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)


def _setup(tmp_path: Path, *, workspace: str = WORKSPACE) -> dict[str, str]:
    bin_dir, suite, runs = tmp_path / "bin", tmp_path / "suite", tmp_path / "runs"
    for directory in (bin_dir, suite / "calibration", runs):
        directory.mkdir(parents=True)
    _executable(bin_dir / "claude", "#!/bin/sh\necho '2.1.288 (Claude Code)'\n")
    _executable(bin_dir / "wiki-studio", "#!/bin/sh\necho 0.4.0\n")
    _executable(bin_dir / "sha256sum", '#!/bin/sh\necho "0000  $1"\n')
    _executable(
        bin_dir / "curl",
        f"#!/bin/sh\nprintf 'HTTP/2 200\\r\\nanthropic-workspace-id: {workspace}\\r\\n\\r\\n'\n",
    )
    (suite / "calibration" / "tasks.txt").write_text("# comment\nlc-retain-rounding\n", encoding="utf-8")
    (suite / "runner.py").write_text(
        "import os, sys\n"
        "open(os.environ['STUB_LOG'], 'a').write('runner\\n')\n"
        "run_id = sys.argv[sys.argv.index('--run-id') + 1]\n"
        "root = sys.argv[sys.argv.index('--run-root') + 1]\n"
        "if os.environ.get('STUB_RUNNER_OUTPUT', '1') == '1':\n"
        "    os.makedirs(os.path.join(root, run_id))\n"
        "    open(os.path.join(root, run_id, 'receipts.jsonl'), 'w').write('{}\\n')\n"
        "sys.exit(int(os.environ['STUB_RUNNER_EXIT']))\n",
        encoding="utf-8",
    )
    (suite / "scan_secrets.py").write_text(
        "import os, sys\n"
        "open(os.environ['STUB_LOG'], 'a').write('scan ' + sys.argv[1] + '\\n')\n"
        "sys.exit(int(os.environ.get('STUB_SCAN_EXIT', '0')))\n",
        encoding="utf-8",
    )
    environment = tmp_path / "environment.txt"
    environment.write_text("# code test\n", encoding="utf-8")
    return {
        "PATH": os.pathsep.join([str(bin_dir), str(Path(sys.executable).parent), "/usr/bin", "/bin"]),
        "CALIBRATION_SUITE_DIR": str(suite),
        "CALIBRATION_RUNS_DIR": str(runs),
        "CALIBRATION_ENVIRONMENT": str(environment),
        "CALIBRATION_RUN_ID": "probe",
        "CODE_SHA": "test",
        "ANTHROPIC_API_KEY": "sk-ant-test-not-a-real-key",
        "CALIBRATION_WORKSPACE_ID": WORKSPACE,
        "STUB_LOG": str(tmp_path / "log.txt"),
        "STUB_RUNNER_EXIT": "0",
    }


def _run(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(RUN_SH), "calibrate"], env=env, capture_output=True, text=True, timeout=60, check=False
    )


def _calibrate(env: dict[str, str]) -> tuple[int, list[str]]:
    completed = _run(env)
    log = Path(env["STUB_LOG"])
    return completed.returncode, log.read_text(encoding="utf-8").splitlines() if log.exists() else []


def _scanned(calls: list[str]) -> bool:
    return any(call.startswith("scan ") for call in calls)


def test_a_clean_run_scans_and_records_the_environment_and_any_override(tmp_path: Path) -> None:
    env = _setup(tmp_path)
    completed = _run(env)
    calls = Path(env["STUB_LOG"]).read_text(encoding="utf-8").splitlines()
    assert completed.returncode == 0 and calls[0] == "runner" and _scanned(calls)
    run_dir = Path(env["CALIBRATION_RUNS_DIR"]) / "probe"
    assert (run_dir / "environment.txt").is_file()
    # the test's own path overrides are evidence too: printed loudly and kept with the run
    assert "WARNING: image paths overridden" in completed.stderr
    recorded = (run_dir / "overrides.txt").read_text(encoding="utf-8")
    assert f"CALIBRATION_ENVIRONMENT={env['CALIBRATION_ENVIRONMENT']}" in recorded
    assert "CALIBRATION_RUNS_DIR=" in recorded and "CALIBRATION_SUITE_DIR=" in recorded


def test_a_failed_environment_copy_still_scans_and_keeps_the_runners_failure(tmp_path: Path) -> None:
    """Review of the calibration container: an unguarded cp under set -e skipped the scan and turned 17 into 1."""
    env = _setup(tmp_path)
    env["STUB_RUNNER_EXIT"] = "17"
    env["CALIBRATION_ENVIRONMENT"] = str(tmp_path / "environment.txt")
    assert _calibrate({**env})[0] == 17  # sanity: copy succeeds, runner failure kept
    Path(env["STUB_LOG"]).unlink()
    shutil.rmtree(Path(env["CALIBRATION_RUNS_DIR"]) / "probe")

    env["CALIBRATION_ENVIRONMENT"] = str(tmp_path / "missing-environment.txt")  # preflight hashes it via the stub
    status, calls = _calibrate(env)
    assert status == 17 and _scanned(calls)


def test_a_failed_copy_after_a_clean_run_is_still_a_failure(tmp_path: Path) -> None:
    env = _setup(tmp_path)
    env["CALIBRATION_ENVIRONMENT"] = str(tmp_path / "missing-environment.txt")
    status, calls = _calibrate(env)
    assert status != 0 and _scanned(calls)


def test_a_scan_hit_fails_a_clean_run_and_stays_loud_when_the_runners_failure_wins(tmp_path: Path) -> None:
    env = _setup(tmp_path)
    env["STUB_SCAN_EXIT"] = "1"
    clean = _run(env)
    assert clean.returncode == 1 and "SECRET SCAN FOUND HITS" in clean.stderr
    shutil.rmtree(Path(env["CALIBRATION_RUNS_DIR"]) / "probe")
    env["STUB_RUNNER_EXIT"] = "17"
    failed = _run(env)
    assert failed.returncode == 17  # the runner's failure is reported first
    assert "SECRET SCAN FOUND HITS" in failed.stderr and "do not commit" in failed.stderr


def test_a_runner_that_wrote_nothing_keeps_its_status_and_has_nothing_to_scan(tmp_path: Path) -> None:
    env = _setup(tmp_path)
    env["STUB_RUNNER_EXIT"] = "17"
    env["STUB_RUNNER_OUTPUT"] = "0"
    status, calls = _calibrate(env)
    assert status == 17 and calls == ["runner"]


def test_a_key_from_another_workspace_never_reaches_the_runner(tmp_path: Path) -> None:
    env = _setup(tmp_path, workspace="wrkspc_other")
    status, calls = _calibrate(env)
    assert status != 0 and calls == []


def test_an_unwritable_runs_directory_never_reaches_the_runner(tmp_path: Path) -> None:
    env = _setup(tmp_path)
    runs = Path(env["CALIBRATION_RUNS_DIR"])
    runs.chmod(0o555)
    try:
        if os.access(runs, os.W_OK):
            pytest.skip("running as a user that ignores directory permissions (root)")
        status, calls = _calibrate(env)
    finally:
        runs.chmod(0o755)
    assert status != 0 and calls == []

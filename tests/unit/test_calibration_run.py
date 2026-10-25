# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""The calibration entry point's exit-status and secret-scan contract (eval/lifecycle-suite/calibration/run.sh).

The real script runs under bash with stub ``curl``, ``claude``, ``wiki-studio``,
runner and scanner, so ``preflight`` is exercised as written and nothing is
bypassed: the stub ``curl`` answers like the Models API with a workspace header.
"""

from __future__ import annotations

import json
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
MODEL, REVISION = "all-MiniLM-L6-v2", "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"


def _executable(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)


def _setup(tmp_path: Path, *, workspace: str = WORKSPACE, cached: str | None = REVISION) -> dict[str, str]:
    bin_dir, suite, runs = tmp_path / "bin", tmp_path / "suite", tmp_path / "runs"
    for directory in (bin_dir, suite / "calibration", runs):
        directory.mkdir(parents=True)
    _executable(bin_dir / "claude", "#!/bin/sh\necho '2.1.288 (Claude Code)'\n")
    _executable(bin_dir / "wiki-studio", "#!/bin/sh\necho 0.4.1\n")
    _executable(bin_dir / "sha256sum", '#!/bin/sh\necho "0000  $1"\n')
    _executable(  # logs to its own file, so a test can tell whether the key was used
        bin_dir / "curl",
        f'#!/bin/sh\necho curl >> "$STUB_CURL_LOG"\n'
        f"printf 'HTTP/2 200\\r\\nanthropic-workspace-id: {workspace}\\r\\n\\r\\n'\n",
    )
    hf_home = tmp_path / "hf"
    model_dir = hf_home / "hub" / f"models--sentence-transformers--{MODEL}"
    if cached is not None:  # the image's cache, as the Dockerfile leaves it
        (model_dir / "refs").mkdir(parents=True)
        (model_dir / "refs" / "main").write_text(cached, encoding="utf-8")
        (model_dir / "snapshots" / cached).mkdir(parents=True)
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
        "CALIBRATION_HF_HOME": str(hf_home),
        "CALIBRATION_RUN_ID": "probe",
        "EMBEDDING_MODEL": MODEL,
        "EMBEDDING_MODEL_REVISION": REVISION,
        "CODE_SHA": "test",
        "ANTHROPIC_API_KEY": "sk-ant-test-not-a-real-key",
        "CALIBRATION_WORKSPACE_ID": WORKSPACE,
        "STUB_LOG": str(tmp_path / "log.txt"),
        "STUB_CURL_LOG": str(tmp_path / "curl.txt"),
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


def test_preflight_prints_the_pinned_embedding_model_revision(tmp_path: Path) -> None:
    env = _setup(tmp_path)
    completed = _run(env)
    assert completed.returncode == 0, completed.stderr
    assert f"embedding model: sentence-transformers/{MODEL} revision {REVISION} (pinned" in completed.stdout


@pytest.mark.parametrize("cached", [None, "0" * 40])
def test_a_cache_without_the_pinned_revision_is_refused_before_the_key_is_used(
    tmp_path: Path, cached: str | None
) -> None:
    """Review of #37: the server runs offline, so a missing or different cached model must show up in preflight,
    before the key is used, not as a server that cannot start."""
    env = _setup(tmp_path, cached=cached)
    completed = _run(env)
    assert completed.returncode != 0 and "not the pinned" in completed.stderr
    assert not Path(env["STUB_CURL_LOG"]).exists() and not Path(env["STUB_LOG"]).exists()


# The measured run (task 18d): the preregistration fixes the run, and preflight's cost check guards the spend limit.

CALIBRATION_RECEIPTS = "eval/lifecycle-suite/calibration/receipts-20261024T033046Z.jsonl"
ANNOUNCEMENT = "https://github.com/gosha70/memkernel/issues/17#issuecomment-1 2026-11-01T09:00:00Z 2026-11-01T09:00:00Z"


def _measure_setup(tmp_path: Path, *, preregistered_limit: float = 150, runs: int = 5) -> dict[str, str]:
    env = _setup(tmp_path)
    repo = tmp_path / "repo"
    suite = repo / "eval" / "lifecycle-suite"  # as in the image: the repository's layout under /opt/memkernel
    shutil.copytree(env["CALIBRATION_SUITE_DIR"], suite)
    for name in ("estimate.py", "records.py"):
        shutil.copy(SUITE_DIR / name, suite / name)
    for config in (SUITE_DIR / "arms").glob("*/config.frozen.json"):
        (suite / "arms" / config.parent.name).mkdir(parents=True)
        shutil.copy(config, suite / "arms" / config.parent.name / config.name)
    shutil.copy(SUITE_DIR.parent.parent / CALIBRATION_RECEIPTS, repo / CALIBRATION_RECEIPTS)
    (suite / "runner.py").write_text(  # logs its arguments, so the test sees what the preregistration fixed
        "import os, sys\n"
        "open(os.environ['STUB_LOG'], 'a').write('runner ' + ' '.join(sys.argv[1:]) + '\\n')\n"
        "root, run_id = sys.argv[sys.argv.index('--run-root') + 1], sys.argv[sys.argv.index('--run-id') + 1]\n"
        "os.makedirs(os.path.join(root, run_id))\n"
        "sys.exit(0)\n",
        encoding="utf-8",
    )
    tasks = sorted(p.name for p in (SUITE_DIR / "tasks").iterdir() if p.is_dir())
    parameters = {
        "model": "claude-sonnet-5-5",
        "tasks": tasks,
        "arms": ["bare", "placebo", "protocol", "claude_md", "fs_grep", "memkernel", "wiki_studio"],
        "runs_per_arm_per_task": runs,
        "prices_usd_per_mtok": {"input": 2.0, "cache_write": 2.5, "cache_read": 0.1, "output": 10.0},
        "prices_as_of": "2026-10-15",
        "invalid_allowance": 0.2,
        "calibration_receipts": CALIBRATION_RECEIPTS,
        "spend_limit_usd": preregistered_limit,
    }
    preregistration = tmp_path / "preregistration.md"
    preregistration.write_text(f"# Preregistration\n\n```json\n{json.dumps(parameters)}\n```\n", encoding="utf-8")
    env.update(
        CALIBRATION_SUITE_DIR=str(suite),
        CALIBRATION_RUN_ID="measured-probe",
        MEASURED_PREREGISTRATION=str(preregistration),
        MEASURED_SPEND_LIMIT=str(preregistered_limit),
        MEASURED_ANNOUNCEMENT=ANNOUNCEMENT,
    )
    return env


def _measure(env: dict[str, str]) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    completed = subprocess.run(
        ["bash", str(RUN_SH), "measure"], env=env, capture_output=True, text=True, timeout=60, check=False
    )
    log = Path(env["STUB_LOG"])
    return completed, log.read_text(encoding="utf-8").splitlines() if log.exists() else []


def test_the_measured_run_is_the_one_the_preregistration_fixes(tmp_path: Path) -> None:
    env = _measure_setup(tmp_path)
    completed, calls = _measure(env)
    assert completed.returncode == 0, completed.stderr
    assert "estimate: $80.74" in completed.stdout and "plus 30%, $104.96, is within the spend limit $150.00" in (
        completed.stdout
    )
    assert "model: claude-sonnet-5-5" in completed.stdout and "preregistration: " in completed.stdout
    runner = next(call for call in calls if call.startswith("runner "))
    assert f"--phase measured --preregistration {env['MEASURED_PREREGISTRATION']}" in runner
    assert "--runs 5 --model claude-sonnet-5-5" in runner and runner.count("--task ") == 20
    assert runner.count("--arm ") == 7 and _scanned(calls)
    assert "measured output: " in completed.stdout
    recorded = Path(env["CALIBRATION_RUNS_DIR"]) / "measured-probe" / "announcement.txt"
    assert recorded.read_text(encoding="utf-8") == ANNOUNCEMENT + "\n"  # SC-5: where and when it was announced


@pytest.mark.parametrize(
    ("preregistered", "entered", "message"),
    [
        (150, "100", "is not the preregistered $150.00"),  # the Console shows another limit than preregistered
        (100, "100", "the estimate plus 30%, $104.96, exceeds the spend limit $100.00"),
    ],
)
def test_the_cost_check_refuses_before_any_paid_session(
    tmp_path: Path, preregistered: float, entered: str, message: str
) -> None:
    env = _measure_setup(tmp_path, preregistered_limit=preregistered)
    env["MEASURED_SPEND_LIMIT"] = entered
    completed, calls = _measure(env)
    assert completed.returncode != 0 and message in completed.stderr
    assert not any(call.startswith("runner") for call in calls)


def test_no_preregistration_no_measured_run(tmp_path: Path) -> None:
    env = _measure_setup(tmp_path)
    env["MEASURED_PREREGISTRATION"] = str(tmp_path / "missing.md")
    completed, calls = _measure(env)
    assert completed.returncode != 0 and "no preregistration" in completed.stderr
    assert calls == [] and not Path(env["STUB_CURL_LOG"]).exists()  # the key was never used


def test_no_announcement_no_measured_run(tmp_path: Path) -> None:
    env = _measure_setup(tmp_path)
    del env["MEASURED_ANNOUNCEMENT"]
    completed, calls = _measure(env)
    assert completed.returncode != 0 and "MEASURED_ANNOUNCEMENT" in completed.stderr
    assert calls == [] and not Path(env["STUB_CURL_LOG"]).exists()  # the key was never used


def test_a_nan_allowance_never_reaches_the_runner(tmp_path: Path) -> None:
    """Review of 18d: NaN made the spend check pass and the stub runner start."""
    env = _measure_setup(tmp_path)
    preregistration = Path(env["MEASURED_PREREGISTRATION"])
    text = preregistration.read_text(encoding="utf-8").replace('"invalid_allowance": 0.2', '"invalid_allowance": NaN')
    preregistration.write_text(text, encoding="utf-8")
    completed, calls = _measure(env)
    assert completed.returncode != 0 and "invalid_allowance" in completed.stderr
    assert not any(call.startswith("runner") for call in calls) and "$nan" not in completed.stdout

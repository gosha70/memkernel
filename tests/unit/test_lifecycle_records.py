# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""Receipts, diagnostics, grading, report and secret scan (FR-015a, FR-017, FR-018)."""

from __future__ import annotations

import copy
import json
import re
import shutil
import subprocess
from typing import TYPE_CHECKING, Any

import pytest

from tests.unit._lifecycle_suite import load

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit

records = load("records")
diagnostics = load("diagnostics")
report = load("report")
scan_secrets = load("scan_secrets")
runner = load("runner")


def _w(ts: str, event: dict[str, Any]) -> dict[str, Any]:
    return {"ts": ts, "event": event}


def _stream(workspace: Path) -> list[dict[str, Any]]:
    return [
        _w(
            "2026-10-16T10:00:00.000Z",
            {
                "type": "system",
                "subtype": "init",
                "session_id": "s",
                "mcp_servers": [{"name": "memkernel", "status": "connected"}],
            },
        ),
        _w(
            "2026-10-16T10:00:01.000Z",
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "a",
                            "name": "Read",
                            "input": {"file_path": str(workspace / "README.md")},
                        },
                        {"type": "tool_use", "id": "b", "name": "mcp__memkernel__recall", "input": {"query": "fact"}},
                    ]
                },
            },
        ),
        _w(
            "2026-10-16T10:00:02.000Z",
            {
                "type": "user",
                "message": {
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "b",
                            "content": json.dumps([{"ref_id": "r1"}, {"ref_id": "r2"}]),
                        },
                    ]
                },
            },
        ),
        _w(
            "2026-10-16T10:00:03.000Z",
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {"type": "tool_use", "id": "c", "name": "mcp__memkernel__get", "input": {"ref_id": "r1"}},
                        {
                            "type": "tool_use",
                            "id": "d",
                            "name": "mcp__memkernel__retain",
                            "input": {"content": "x", "type": "fact"},
                        },
                    ]
                },
            },
        ),
        _w("2026-10-16T10:00:04.000Z", {"type": "system", "subtype": "compact_boundary"}),
        _w(
            "2026-10-16T10:00:05.000Z",
            {
                "type": "result",
                "result": "done",
                "usage": {
                    "input_tokens": 100,
                    "cache_creation_input_tokens": 20,
                    "cache_read_input_tokens": 300,
                    "output_tokens": 7,
                },
            },
        ),
    ]


def test_summary_and_diagnostics_are_counts_with_denominators(tmp_path: Path) -> None:
    summary = records.summarise(_stream(tmp_path))
    assert summary.init_seen and summary.mcp_status == {"memkernel": "connected"}
    assert summary.compactions == ["2026-10-16T10:00:04.000Z"]
    assert summary.tokens == {"input": 100, "cache_write": 20, "cache_read": 300, "output": 7}
    assert records.tool_counts(summary)["Read"] == 1

    hooks = [
        {"event": "PreCompact", "exit_status": 0, "ts": "t"},
        {"event": "PostCompact", "exit_status": 1, "ts": "t"},
    ]
    result = diagnostics.session_diagnostics(summary, tmp_path, {"README.md"}, hooks)
    assert result == {
        "re_reads_after_resume": {"numerator": 1, "denominator": 1},
        "calls_before_first_retain": {"numerator": 3, "denominator": 4},
        "recall_to_use": {"numerator": 1, "denominator": 2},
        "hooks_succeeded": {"numerator": 1, "denominator": 2},
        "wiki_studio_nested_model_calls": {"numerator": 0, "denominator": 0},
        "direct_wiki_writes": {"numerator": 0, "denominator": 0},
    }


def _receipt(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "schema_version": 3,
        "run_id": "r",
        "phase": "measured",
        "chain_id": "t.memkernel.r0",
        "position": 0,
        "chain_length": 1,
        "stage": "evaluation",
        "namespace_sha256": "n",
        "arm": "memkernel",
        "task_id": "t",
        "group": "lc-retain",
        "run_index": 0,
        "started_at": "2026-10-16T10:00:00.000Z",
        "ended_at": "2026-10-16T10:01:00.000Z",
        "model": "m",
        "code_sha": "c",
        "arm_config_sha256": "a",
        "preregistration_sha256": "p",
        "valid": True,
        "invalid_reason": None,
        "outcome": "passed",
        "checker_passed": True,
        "hooks": [],
        "tool_calls": {},
        "tokens": {"input": 1, "cache_write": 0, "cache_read": 0, "output": 1},
        "compaction_tokens_estimate": 0,
        "compaction_estimates_missing": 0,
        "api_errors": {},
        "wall_time_ms": 1,
        "stages": {"exposure_at": None, "evaluation_at": None, "compactions": []},
        "diagnostics": {},
        "hashes": {"prompt": "x", "response": "y", "tool_payloads": "z"},
    }
    base.update(overrides)
    return base


def test_receipt_schema_accepts_a_valid_receipt_and_rejects_drift() -> None:
    assert records.validate_receipt(_receipt()) == []
    assert any(
        "missing started_at" in e
        for e in records.validate_receipt({k: v for k, v in _receipt().items() if k != "started_at"})
    )
    assert any(
        "not in" in e for e in records.validate_receipt(_receipt(invalid_reason="timeout"))
    )  # timeouts are never invalid
    assert any("unexpected key" in e for e in records.validate_receipt(_receipt(content="leaked text")))
    # only schema version 3: older receipts are refused here (the report reads version 2 for calibration only)
    assert any("not in [3]" in e for e in records.validate_receipt(_receipt(schema_version=2)))
    assert any("not in [3]" in e for e in records.validate_receipt(_receipt(schema_version=1)))
    assert any(
        "missing api_errors" in e
        for e in records.validate_receipt({k: v for k, v in _receipt().items() if k != "api_errors"})
    )
    assert any("below the minimum 0" in e for e in records.validate_receipt(_receipt(api_errors={"529": -1})))
    assert any("below the minimum 0" in e for e in records.validate_receipt(_receipt(compaction_tokens_estimate=-1)))
    assert any("below the minimum 0" in e for e in records.validate_receipt(_receipt(compaction_estimates_missing=-1)))
    assert any(
        "missing compaction_tokens_estimate" in e
        for e in records.validate_receipt({k: v for k, v in _receipt().items() if k != "compaction_tokens_estimate"})
    )


def _trial(arm: str, task: str, run: int, **overrides: Any) -> dict[str, Any]:
    return _receipt(arm=arm, task_id=task, run_index=run, chain_id=f"{task}.{arm}.r{run}", **overrides)


PARAMS = {
    "title": "memkernel 0.5.0 lifecycle evaluation",
    "code_sha": "c0de",
    "preregistration_commit": "p1",
    "tag": "v0.5.0",
    "model": "m",
    "arms": ["bare", "placebo", "protocol", "claude_md", "fs_grep", "memkernel", "wiki_studio"],
    "primary_comparators": ["claude_md", "fs_grep"],
    "secondary_comparators": ["bare"],
    "min_pairs_inferential": 30,
    "min_tasks_inferential": 2,
    "alpha": 0.05,
    "no_gain_band_points": 10,
    "bootstrap_resamples": 2000,
    "bootstrap_seed": 17,
    "min_valid_pairs_lc_compact": 3,
    "min_valid_pairs_wiki_studio": 2,
    "live_compaction_proven": "yes",
}


def test_report_keeps_valid_failures_and_removes_only_invalid_pairs() -> None:
    receipts = [
        _trial("memkernel", "t1", 0),
        _trial("claude_md", "t1", 0, outcome="failed", checker_passed=False),
        _trial("memkernel", "t2", 0, outcome="timeout", checker_passed=None),
        _trial("claude_md", "t2", 0),
        _trial(
            "memkernel", "t3", 0, valid=False, invalid_reason="mcp_not_connected", outcome=None, checker_passed=None
        ),
        _trial("claude_md", "t3", 0),
        _trial("memkernel", "t9", 0, phase="calibration"),
    ]
    text = report.render(receipts, PARAMS)
    assert "Maintainer-run supplemental evaluation" in text
    assert "the memory store alone against files alone" in text
    assert "| memkernel | 3 | 2 | 1/2 (50%) | 0 | 1 | 0 | mcp_not_connected: 1 |" in text  # the timeout stays a failure
    assert "| claude_md (primary) | 2 | 0 | 1 | 1 | 0 | 1 |" in text
    assert "Descriptive" in text and "Calibration (not scored)" in text and "- Sessions: 1" in text
    assert report.render(copy.deepcopy(receipts), PARAMS) == text  # deterministic


def test_lc_compact_below_the_minimum_is_reported_as_not_measured() -> None:
    receipts = [
        _trial("memkernel", "c1", 0, group="lc-compact"),
        _trial("claude_md", "c1", 0, group="lc-compact"),
        _trial("fs_grep", "c1", 0, group="lc-compact"),
    ]
    assert "**Not measured:** fewer than 3 valid pairs" in report.render(receipts, PARAMS)


class _Final:
    def __init__(self, workspace: Path, response: str = "done", timed_out: bool = False) -> None:
        self.receipt = _receipt(
            group="lc-compact",
            outcome=None,
            checker_passed=None,
            hooks=[
                {"event": "PreCompact", "exit_status": 0, "ts": "t"},
                {"event": "PostCompact", "exit_status": 2, "ts": "t"},
            ],
        )
        self.dirs = runner.SessionDirs(workspace, workspace, workspace, workspace, None, None, "primary")
        self.summary = records.StreamSummary(result_texts=[response])
        self.timed_out = timed_out


def _passing_task(tmp_path: Path) -> object:
    root = tmp_path / "task"
    root.mkdir()
    (root / "checker.py").write_text("def check(workdir, oracle_dir):\n    return True, 'ok'\n", encoding="utf-8")
    return runner.Task("c1", "lc-compact", root, (), None)


def test_a_failed_hook_is_a_valid_failure_not_an_exclusion(tmp_path: Path) -> None:
    final = _Final(tmp_path)
    cfg = runner.RunConfig(tmp_path, "r", "measured", "m", "c", "p", ("x",), "x", "x", tmp_path, tmp_path)
    runner.grade(_passing_task(tmp_path), runner.load_arm("memkernel"), final, cfg)
    assert final.receipt["valid"] is True
    assert final.receipt["checker_passed"] is True and final.receipt["outcome"] == "failed"


def test_a_timeout_is_a_valid_failure(tmp_path: Path) -> None:
    final = _Final(tmp_path, timed_out=True)
    cfg = runner.RunConfig(tmp_path, "r", "measured", "m", "c", "p", ("x",), "x", "x", tmp_path, tmp_path)
    runner.grade(_passing_task(tmp_path), runner.load_arm("memkernel"), final, cfg)
    assert final.receipt["valid"] is True and final.receipt["outcome"] == "timeout"


def test_a_crashing_checker_is_the_only_grading_exclusion(tmp_path: Path) -> None:
    root = tmp_path / "task"
    root.mkdir()
    (root / "checker.py").write_text(
        "def check(workdir, oracle_dir):\n    raise RuntimeError('bug')\n", encoding="utf-8"
    )
    final = _Final(tmp_path)
    cfg = runner.RunConfig(tmp_path, "r", "measured", "m", "c", "p", ("x",), "x", "x", tmp_path, tmp_path)
    runner.grade(runner.Task("c1", "lc-compact", root, (), None), runner.load_arm("bare"), final, cfg)
    assert final.receipt["valid"] is False and final.receipt["invalid_reason"] == "checker_crashed"


def test_secret_scan_trips_on_planted_secrets_and_never_prints_them(tmp_path: Path) -> None:
    planted = {  # assembled at runtime so no credential-shaped literal is committed
        "anthropic": "sk-ant-" + "a" * 24,
        "aws": "AKIA" + "B" * 16,
        "github": "ghp_" + "c" * 36,
        "assignment": "MY_API_KEY=" + "d" * 12,
        "url": "https://user:" + "pw" * 5 + "@example.com/x",
        "pem": "-----BEGIN RSA " + "PRIVATE KEY-----",
    }
    results = tmp_path / "results"
    results.mkdir()
    (results / "receipts.jsonl").write_text("\n".join(planted.values()) + "\n", encoding="utf-8")
    (tmp_path / "clean").mkdir()
    (tmp_path / "clean" / "receipts.jsonl").write_text(json.dumps(_receipt()) + "\n", encoding="utf-8")

    hits = scan_secrets.scan([results])
    assert len(hits) >= len(planted)
    assert not any(secret in hit for hit in hits for secret in planted.values())
    assert scan_secrets.scan([tmp_path / "clean"]) == []
    assert scan_secrets.main([str(results)]) == 1


def test_a_quiet_process_still_times_out(tmp_path: Path) -> None:
    import sys
    import time

    started = time.monotonic()
    result = runner._run_step(
        [sys.executable, "-c", "import time; time.sleep(5)"],
        tmp_path,
        {"PATH": "/usr/bin:/bin"},
        0.2,
        tmp_path / "raw.jsonl",
    )
    assert result.timed_out is True
    assert time.monotonic() - started < 3


def test_an_earlier_session_timeout_makes_the_trial_a_timeout(tmp_path: Path) -> None:
    final = _Final(tmp_path)
    final.receipt["hooks"] = [
        {"event": "PreCompact", "exit_status": 0, "ts": "t"},
        {"event": "PostCompact", "exit_status": 0, "ts": "t"},
    ]
    cfg = runner.RunConfig(tmp_path, "r", "measured", "m", "c", "p", ("x",), "x", "x", tmp_path, tmp_path)
    runner.grade(_passing_task(tmp_path), runner.load_arm("memkernel"), final, cfg, earlier_timeout=True)
    assert final.receipt["valid"] is True and final.receipt["outcome"] == "timeout"

    receipts = [
        _trial(
            "memkernel", "t1", 0, position=0, chain_length=2, stage="exposure", outcome="timeout", checker_passed=None
        ),
        _trial("memkernel", "t1", 0, position=1, chain_length=2, stage="evaluation"),
    ]
    (trial,) = report.assemble(receipts)
    assert trial.valid and trial.outcome == "timeout"


def test_one_successful_hook_never_masks_a_failed_execution(tmp_path: Path) -> None:
    final = _Final(tmp_path)
    final.receipt["hooks"] = [
        {"event": "PreCompact", "exit_status": 0, "ts": "t"},
        {"event": "PostCompact", "exit_status": 1, "ts": "t1"},
        {"event": "PostCompact", "exit_status": 0, "ts": "t2"},
    ]
    cfg = runner.RunConfig(tmp_path, "r", "measured", "m", "c", "p", ("x",), "x", "x", tmp_path, tmp_path)
    runner.grade(_passing_task(tmp_path), runner.load_arm("memkernel"), final, cfg)
    assert final.receipt["checker_passed"] is True and final.receipt["outcome"] == "failed"


def test_separate_runs_stay_separate_and_order_does_not_matter() -> None:
    run_a = [
        _trial("memkernel", "t1", 0, run_id="a", outcome="failed", checker_passed=False),
        _trial("claude_md", "t1", 0, run_id="a"),
    ]
    run_b = [_trial("memkernel", "t1", 0, run_id="b"), _trial("claude_md", "t1", 0, run_id="b")]
    forward, backward = report.assemble(run_a + run_b), report.assemble(run_b + run_a)
    assert forward == backward and len(forward) == 4
    assert report.render(run_a + run_b, PARAMS) == report.render(run_b + run_a, PARAMS)
    assert "| claude_md (primary) | 2 | 1 | 0 | 1 | 0 | 0 |" in report.render(run_a + run_b, PARAMS)

    with pytest.raises(ValueError, match="duplicate receipt"):
        report.assemble(run_a + run_a)


def test_closing_stdout_before_exiting_still_times_out(tmp_path: Path) -> None:
    import sys
    import time

    script = "import os, sys, time; print('{}', flush=True); os.close(sys.stdout.fileno()); time.sleep(5)"
    started = time.monotonic()
    result = runner._run_step(
        [sys.executable, "-c", script], tmp_path, {"PATH": "/usr/bin:/bin"}, 0.3, tmp_path / "raw.jsonl"
    )
    assert result.timed_out is True
    assert time.monotonic() - started < 3


def _stub_run(
    root: Path, monkeypatch: pytest.MonkeyPatch, phase: str, arms: list[str], tasks: tuple[str, ...] = ("demo-retain",)
) -> list[dict[str, Any]]:
    """One chain per task and arm (demo-retain by default) through the real runner with the stub agent."""
    import sys as _sys

    root.mkdir()
    cfg = runner.RunConfig(
        run_root=root,
        run_id=phase,
        phase=phase,
        model="stub",
        code_sha="c",
        preregistration_sha256="p" if phase == "measured" else None,
        agent_cmd=(_sys.executable, str(runner.SUITE_DIR / "stub_agent.py")),
        memkernel_cmd="stub",
        memkernel_python=_sys.executable,
        tasks_root=runner.SUITE_DIR / "fixtures" / "demo-tasks",
        oracles_root=runner.SUITE_DIR / "fixtures" / "demo-oracles",
        timeout_s=60.0,
        hook_command_override=(_sys.executable, "-c", "import sys; sys.stdin.read()"),
    )
    monkeypatch.setattr(runner, "_inside_checkout", lambda path: False)
    path = runner.run(cfg, list(tasks), arms, runs=1)
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_calibration_runs_are_never_graded_and_measured_runs_are(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Calibration receipts carry usage and stream evidence only; measured grading is unchanged."""
    graded: list[str] = []
    real_grade = runner.grade

    def spy(task: object, arm: object, final: object, cfg: object, earlier_timeout: bool = False) -> None:
        graded.append(cfg.phase)  # type: ignore[attr-defined]
        real_grade(task, arm, final, cfg, earlier_timeout=earlier_timeout)

    monkeypatch.setattr(runner, "grade", spy)

    calibration = _stub_run(tmp_path / "calibration", monkeypatch, "calibration", ["bare"])
    evaluation = [r for r in calibration if r["stage"] == "evaluation"]
    assert evaluation and all(r["outcome"] is None and r["checker_passed"] is None for r in evaluation)
    assert "calibration" not in graded

    measured = _stub_run(tmp_path / "measured", monkeypatch, "measured", ["bare"])
    assert [r["outcome"] for r in measured if r["stage"] == "evaluation"] == ["passed"]
    assert graded == ["measured"]


def test_calibration_keeps_only_receipts_and_streams_so_nothing_can_be_graded_by_hand(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    arms = ["bare", "claude_md", "fs_grep", "memkernel"]  # workspace, transcript and store carry-over all covered
    _stub_run(tmp_path / "calibration", monkeypatch, "calibration", arms)
    run_dir = tmp_path / "calibration" / "calibration"
    kept = sorted(p.relative_to(run_dir).as_posix() for p in run_dir.rglob("*") if p.is_file())
    streams = [path for path in kept if path != "receipts.jsonl"]
    assert "receipts.jsonl" in kept and len(streams) == len(arms) * 2  # demo-retain has two sessions
    assert all(re.fullmatch(r"[^/]+/s\d+/stream\.jsonl", path) for path in streams), kept
    assert not any(p.name == "workspace" for p in run_dir.rglob("*"))

    _stub_run(tmp_path / "measured", monkeypatch, "measured", ["bare"])
    measured = tmp_path / "measured" / "measured"
    assert any(p.name == "workspace" and p.is_dir() for p in measured.rglob("*"))  # measured runs keep everything


def test_calibration_cleanup_never_follows_a_symlink_out_of_the_chain(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    (outside / "sub").mkdir(parents=True)
    (outside / "sentinel.txt").write_text("keep\n", encoding="utf-8")
    (outside / "sub" / "sentinel.txt").write_text("keep\n", encoding="utf-8")
    chain = tmp_path / "chain"
    (chain / "s0" / "workspace").mkdir(parents=True)
    (chain / "s0" / runner.STREAM_FILE).write_text("{}\n", encoding="utf-8")
    (chain / "s42").symlink_to(outside, target_is_directory=True)  # looks like a session directory
    (chain / "s0" / "home").symlink_to(outside / "sub", target_is_directory=True)  # a link inside a session
    (chain / "memory").symlink_to(outside, target_is_directory=True)

    runner.discard_session_state(chain)

    assert sorted(p.relative_to(chain).as_posix() for p in chain.rglob("*")) == ["s0", "s0/stream.jsonl"]
    assert (outside / "sentinel.txt").read_text(encoding="utf-8") == "keep\n"
    assert (outside / "sub" / "sentinel.txt").read_text(encoding="utf-8") == "keep\n"


def test_calibration_cleanup_refuses_a_chain_root_that_is_a_symlink(tmp_path: Path) -> None:
    unrelated = tmp_path / "unrelated"
    (unrelated / "s0" / "workspace").mkdir(parents=True)
    (unrelated / "keep.txt").write_text("keep\n", encoding="utf-8")
    (unrelated / "s0" / "workspace" / "keep.txt").write_text("keep\n", encoding="utf-8")
    chain = tmp_path / "chain"
    chain.symlink_to(unrelated, target_is_directory=True)

    with pytest.raises(OSError, match="not a real directory"):
        runner.discard_session_state(chain)

    assert (unrelated / "keep.txt").read_text(encoding="utf-8") == "keep\n"
    assert (unrelated / "s0" / "workspace" / "keep.txt").is_file()
    assert chain.is_symlink()


def test_a_directory_swapped_for_a_link_mid_cleanup_is_not_followed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("keep\n", encoding="utf-8")
    chain = tmp_path / "chain"
    (chain / "s0" / "workspace").mkdir(parents=True)
    (chain / "s0" / runner.STREAM_FILE).write_text("{}\n", encoding="utf-8")
    real_remove = runner._remove_entry

    def swap_then_remove(name: str, is_dir: bool, parent_fd: int) -> None:
        if name == "workspace":  # scanned as a directory, now a link to elsewhere
            shutil.rmtree(chain / "s0" / "workspace")
            (chain / "s0" / "workspace").symlink_to(outside, target_is_directory=True)
        real_remove(name, is_dir, parent_fd)

    monkeypatch.setattr(runner, "_remove_entry", swap_then_remove)
    with pytest.raises(OSError):
        runner.discard_session_state(chain)
    assert (outside / "keep.txt").read_text(encoding="utf-8") == "keep\n"


def test_a_symlinked_chain_root_stops_a_calibration_run_with_the_receipts_on_disk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A chain directory swapped for a link once its sessions end (an agent's leftover process could do it)."""
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    (unrelated / "keep.txt").write_text("keep\n", encoding="utf-8")
    real_run_chain = runner.run_chain

    def run_then_swap(task: object, arm: object, run_index: int, cfg: object, observe: object = None) -> object:
        receipts = real_run_chain(task, arm, run_index, cfg, observe)  # type: ignore[arg-type]
        chain = runner.chain_dir_for(task, arm, run_index, cfg)  # type: ignore[arg-type]
        shutil.rmtree(chain)
        chain.symlink_to(unrelated, target_is_directory=True)
        return receipts

    monkeypatch.setattr(runner, "run_chain", run_then_swap)
    with pytest.raises(SystemExit, match="calibration cleanup failed"):
        _stub_run(tmp_path / "calibration", monkeypatch, "calibration", ["bare"])

    assert (unrelated / "keep.txt").read_text(encoding="utf-8") == "keep\n"
    receipts = (tmp_path / "calibration" / "calibration" / "receipts.jsonl").read_text(encoding="utf-8")
    assert len(receipts.splitlines()) == 2


def test_a_failed_calibration_cleanup_stops_the_run_with_the_receipts_on_disk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(chain_dir: Path) -> None:
        raise PermissionError(13, "Permission denied", str(chain_dir))

    monkeypatch.setattr(runner, "discard_session_state", refuse)
    with pytest.raises(SystemExit, match="calibration cleanup failed"):
        _stub_run(tmp_path / "calibration", monkeypatch, "calibration", ["bare", "fs_grep"])

    receipts = (tmp_path / "calibration" / "calibration" / "receipts.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(receipts) == 2  # the first chain's two sessions, written before cleanup was attempted
    assert {json.loads(line)["arm"] for line in receipts} == {"bare"}  # the run stopped at the failure


def test_calibration_report_shows_per_session_usage_ranges_by_token_class() -> None:
    receipts = [
        _trial(
            "memkernel",
            "t9",
            0,
            phase="calibration",
            outcome=None,
            checker_passed=None,
            tokens={"input": 10, "cache_write": 100, "cache_read": 1000, "output": 5},
        ),
        _trial(
            "memkernel",
            "t9",
            1,
            phase="calibration",
            outcome=None,
            checker_passed=None,
            tokens={"input": 30, "cache_write": 300, "cache_read": 3000, "output": 15},
        ),
        _trial(
            "bare",
            "t9",
            0,
            phase="calibration",
            outcome=None,
            checker_passed=None,
            tokens={"input": 7, "cache_write": 0, "cache_read": 70, "output": 2},
        ),
    ]
    text = report.render(receipts, PARAMS)
    assert "| memkernel | 2 | 10 / 20 / 30 | 100 / 200 / 300 | 1000 / 2000 / 3000 | 5 / 10 / 15 |" in text
    assert "| bare | 1 | 7 / 7 / 7 | 0 / 0 / 0 | 70 / 70 / 70 | 2 / 2 / 2 |" in text
    assert "not graded" in text


def test_calibration_usage_medians_print_as_counts_not_in_exponent_form() -> None:
    def session(arm: str, index: int, count: int) -> dict[str, Any]:
        tokens = {"input": count, "cache_write": count, "cache_read": count, "output": count}
        return _trial(arm, "t9", index, phase="calibration", outcome=None, checker_passed=None, tokens=tokens)

    text = report.render(
        [session("memkernel", 0, 1_234_567), session("bare", 0, 999_999), session("bare", 1, 1_000_002)], PARAMS
    )
    assert "| memkernel | 1 | 1234567 / 1234567 / 1234567 |" in text
    assert "999999 / 1000000.5 / 1000002" in text
    assert "e+" not in text


def _use(name: str, **fields: Any) -> Any:
    return records.ToolUse(ts="t", name=name, tool_id=f"{name}-{len(fields)}-{sorted(fields.items())}", input=fields)


def test_wiki_studio_diagnostics_count_nested_models_and_writes_that_bypass_the_gate(tmp_path: Path) -> None:
    summary = records.StreamSummary(
        tool_uses=[
            _use("Bash", command='wiki-studio find "retry backoff"'),
            _use("Bash", command='cd x && wiki-studio --root . query "what is the backoff?"'),
            _use("Bash", command="/opt/bin/wiki-studio ingest notes.md; echo done"),
            _use("Bash", command='wiki-studio propose --from "$D" --promote'),
            _use("Bash", command='grep -r "query" knowledge/wiki'),  # the word, not the verb
            _use("Write", file_path=str(tmp_path / "knowledge" / "wiki" / "decisions" / "x.md")),
            _use("Edit", file_path="knowledge/wiki/index.md"),
            _use("Write", file_path=str(tmp_path / "backoff.py")),
            _use("Write", file_path=str(tmp_path / "knowledge" / "wikipedia.md")),
        ]
    )
    result = diagnostics.session_diagnostics(summary, tmp_path, set(), [])
    assert result["wiki_studio_nested_model_calls"] == {"numerator": 2, "denominator": 5}
    assert result["direct_wiki_writes"] == {"numerator": 2, "denominator": 4}


def test_an_arm_outside_its_groups_gets_no_chain_and_no_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pinned: list[str] = []
    monkeypatch.setattr(runner, "check_cli_pin", lambda arm: pinned.append(arm.name))
    receipts = _stub_run(tmp_path / "measured", monkeypatch, "measured", ["wiki_studio", "bare"])  # demo-retain only
    assert {r["arm"] for r in receipts} == {"bare"}
    assert not (tmp_path / "measured" / "measured" / "demo-retain.wiki_studio.r0").exists()
    assert pinned == ["wiki_studio", "bare"]  # every arm is checked before a paid run starts


def _fake_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, output: str | None) -> None:
    import os

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    if output is not None:
        script = bin_dir / "wiki-studio"
        script.write_text(f"#!/bin/sh\necho '{output}'\n", encoding="utf-8")
        script.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}/usr/bin{os.pathsep}/bin")


@pytest.mark.parametrize(("output", "accepted"), [("0.4.1", True), ("0.4.0", False), ("0.3.1", False), (None, False)])
def test_a_paid_run_refuses_to_start_unless_the_pinned_cli_version_is_on_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, output: str | None, accepted: bool
) -> None:
    _fake_cli(tmp_path, monkeypatch, output)
    arm = runner.load_arm("wiki_studio")
    if accepted:
        runner.check_cli_pin(arm)
    else:
        with pytest.raises(SystemExit, match="wiki_studio"):
            runner.check_cli_pin(arm)
    runner.check_cli_pin(runner.load_arm("bare"))  # arms without a pin never look


def test_the_demo_runs_no_cli_check(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_cli(tmp_path, monkeypatch, None)  # no wiki-studio on PATH at all
    monkeypatch.setattr(runner, "_inside_checkout", lambda path: False)
    assert runner.demo() == 0


def test_the_report_gives_wiki_studio_its_own_table_outside_memkernels_label() -> None:
    receipts = [
        _trial("memkernel", "w1", 0, group="lc-wiki"),
        _trial("claude_md", "w1", 0, group="lc-wiki", outcome="failed", checker_passed=False),
        _trial("fs_grep", "w1", 0, group="lc-wiki", outcome="failed", checker_passed=False),
        _trial("wiki_studio", "w1", 0, group="lc-wiki"),
    ]
    text = report.render(receipts, PARAMS)
    assert "| wiki_studio vs | Valid pairs |" in text
    assert "| claude_md (primary) | 1 | 0 | 1 | 0 | 0 | 0 |" in text
    assert "**wiki_studio not measured:** fewer than 2 valid pairs" in text
    assert "| wiki_studio (primary)" not in text and "| wiki_studio (secondary)" not in text  # never a comparator
    without = report.render([r for r in receipts if r["arm"] != "wiki_studio"], PARAMS)
    label = text.split("## Label", 1)[1].split("##", 1)[0]
    assert label == without.split("## Label", 1)[1].split("##", 1)[0]  # memkernel's label is unchanged


@pytest.mark.parametrize(
    ("command", "verbs"),
    [
        ("echo wiki-studio query", []),
        ("wiki-studio \\\nquery q", ["query"]),  # backslash-newline continuation (review of #31)
        ("printf '%s\\n' ';' wiki-studio query", []),  # a quoted separator is text
        ("# $(wiki-studio query q)\necho done", []),  # a comment runs nothing
        ("echo hi # wiki-studio query", []),
        ("cat > /dev/null <<EOF\n$(wiki-studio query x)\nEOF", ["query"]),  # unquoted heredoc expands
        ("cat > /dev/null <<'EOF'\n$(wiki-studio query x)\nEOF", []),  # quoted heredoc does not
        ("wiki-studio query q > out.txt 2>&1", ["query"]),
        (">out.txt wiki-studio ingest b", ["ingest"]),
        ("if true; then wiki-studio query q; fi", ["query"]),
        ("{ wiki-studio ingest a; }", ["ingest"]),
        ("true || wiki-studio query q", ["query"]),  # static: a conditional command still counts
        ('cat <<< "hello"\nwiki-studio query q', ["query"]),  # a here-string has no body (review of #31)
        ("cat <<EOF\n'$(wiki-studio query q)'\nEOF", ["query"]),  # body quotes do not stop expansion
        ('cat <<< "$(wiki-studio ingest a)"', ["ingest"]),
        ("cat <<EOF\n\\$(wiki-studio query q)\nEOF", []),  # an escaped $ is literal in a heredoc
        ('eval "wiki-studio query q"', ["query"]),
        ("sh <<EOF\nwiki-studio query q\nEOF", ["query"]),  # a shell reading its script from a heredoc
        ("w=wiki-studio; $w query q", []),  # known gap: the program is only known at run time
        ("printf 'wiki-studio ingest notes.md\\n'", []),
        ('grep -rn "wiki-studio query" README.md', []),
        ("cat > HOWTO.md <<EOF\nwiki-studio query 'x'\nEOF", []),
        ("echo '$(wiki-studio query q)'", []),
        ("env FOO=1 wiki-studio query q", ["query"]),
        ("X=1 wiki-studio --root . ingest a.md", ["ingest"]),
        ("bash -c 'wiki-studio ingest notes.md'", ["ingest"]),
        ("python3 -m wiki_studio query q", ["query"]),
        ('echo "$(wiki-studio query q)"', ["query"]),
        ("(cd a && wiki-studio query q) | tee out", ["query"]),
        ('wiki-studio propose --from "$D" --promote', ["propose"]),
    ],
)
def test_only_executed_wiki_studio_commands_count(command: str, verbs: list[str]) -> None:
    """Printed or quoted command examples are text, not executions (review of task 17a)."""
    assert diagnostics._wiki_studio_verbs(command) == verbs


def test_the_report_shows_both_new_diagnostics_and_flags_a_nested_model() -> None:
    def trial(arm: str, nested: tuple[int, int], writes: tuple[int, int]) -> dict[str, Any]:
        diag = {
            "wiki_studio_nested_model_calls": {"numerator": nested[0], "denominator": nested[1]},
            "direct_wiki_writes": {"numerator": writes[0], "denominator": writes[1]},
        }
        return _trial(arm, "w1", 0, group="lc-wiki", diagnostics=diag)

    clean = report.render([trial("wiki_studio", (0, 3), (0, 1)), trial("claude_md", (0, 2), (2, 2))], PARAMS)
    assert "| wiki_studio | 0/3 | 0/1 |" in clean and "| claude_md | 0/2 | 2/2 |" in clean
    assert "Token accounting incomplete" not in clean

    nested = report.render([trial("wiki_studio", (1, 3), (2, 2)), trial("claude_md", (0, 2), (2, 2))], PARAMS)
    assert "| wiki_studio | 1/3 | 2/2 |" in nested
    assert "**Token accounting incomplete:** 1 Bash call(s) in this group ran `wiki-studio ingest`" in nested
    assert nested != clean


def test_an_absent_preregistered_comparator_counts_as_zero_pairs() -> None:
    receipts = [
        _trial("wiki_studio", "w1", 0, group="lc-wiki"),
        _trial("claude_md", "w1", 0, group="lc-wiki"),
        _trial("wiki_studio", "w2", 0, group="lc-wiki"),
        _trial("claude_md", "w2", 0, group="lc-wiki"),
    ]  # no fs_grep receipts at all
    text = report.render(receipts, PARAMS)
    second = text.split("| wiki_studio vs |", 1)[1]
    assert "| claude_md (primary) | 2 |" in second and "| fs_grep (primary) | 0 |" in second
    assert "**wiki_studio not measured:** fewer than 2 valid pairs" in text

    lenient = {**PARAMS, "min_pairs_inferential": 1}
    memkernel_only_vs_claude_md = report.render([_trial("memkernel", "t1", 0), _trial("claude_md", "t1", 0)], lenient)
    assert "| fs_grep (primary) | 0 |" in memkernel_only_vs_claude_md
    assert "Descriptive:" in memkernel_only_vs_claude_md  # a missing primary comparator is never inferential


BASH_AGREEMENT_CASES = [  # every case here runs the same way whatever the conditions evaluate to
    "wiki-studio find 'retry backoff'",
    "wiki-studio \\\nquery q",
    "printf '%s\\n' ';' wiki-studio query",
    "# $(wiki-studio query q)\necho done",
    "echo wiki-studio query",
    'grep -rn "wiki-studio query" . || true',
    "cat > /dev/null <<EOF\nwiki-studio query x\nEOF",
    "cat > /dev/null <<EOF\n$(wiki-studio query x)\nEOF",
    "cat > /dev/null <<'EOF'\n$(wiki-studio query x)\nEOF",
    "echo '$(wiki-studio query q)'",
    'echo "$(wiki-studio query q)"',
    "x=`wiki-studio ingest a`",
    "env FOO=1 wiki-studio query q",
    "bash -c 'wiki-studio ingest notes.md'",
    "(cd a && wiki-studio query q) | cat",
    "wiki-studio query q > out.txt 2>&1",
    "if true; then wiki-studio query q; fi",
    'echo "a;b" && wiki-studio propose --from "$D" --promote',
    'echo "$(echo wiki-studio query)"',
    'cat <<< "hello"\nwiki-studio query q',
    "cat <<EOF\n'$(wiki-studio query q)'\nEOF",
    'cat <<< "$(wiki-studio ingest a)"',
    "cat <<EOF\n\\$(wiki-studio query q)\nEOF",
    'cat <<EOF\n"`wiki-studio ingest b`"\nEOF\nwiki-studio lint',
    'eval "wiki-studio query q"',
    "sh <<EOF\nwiki-studio query q\nEOF",
    "cat <<-EOF\n\t$(wiki-studio query q)\n\tEOF",
    "wiki-studio query q & wait",
    '"wiki-studio" query q',
    "for i in 1; do wiki-studio ingest a; done",
    "case x in x) wiki-studio query q;; esac",
    "echo $(( 1 << 2 )); wiki-studio lint",
    'echo "#" wiki-studio query',
    "cat <<EOF; wiki-studio lint\nbody $(wiki-studio query q)\nEOF",
]


@pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")
def test_the_detector_agrees_with_bash_on_what_runs(tmp_path: Path) -> None:
    """Ground truth: Bash itself runs each case against a stub wiki-studio that logs its verb."""
    (tmp_path / "bin").mkdir()
    (tmp_path / "a").mkdir()
    log = tmp_path / "log"
    stub = tmp_path / "bin" / "wiki-studio"
    stub.write_text(
        '#!/bin/sh\nfor a in "$@"; do case "$a" in --root|--wiki-dir|--proposals-dir|--backend|--output-dir) '
        'skip=1; continue;; --*) continue;; esac; if [ -n "$skip" ]; then skip=; continue; fi; '
        f"echo \"$a\" >> '{log}'; break; done\n",
        encoding="utf-8",
    )
    stub.chmod(0o755)
    env = {"PATH": f"{tmp_path / 'bin'}:/usr/bin:/bin", "D": str(tmp_path)}
    for case in BASH_AGREEMENT_CASES:
        log.unlink(missing_ok=True)
        subprocess.run(["bash", "-c", case], cwd=tmp_path, env=env, capture_output=True, timeout=20, check=False)
        executed = log.read_text(encoding="utf-8").split() if log.exists() else []
        assert diagnostics._wiki_studio_verbs(case) == executed, case


def test_the_compaction_estimate_sums_pre_tokens_and_stays_out_of_the_token_classes() -> None:
    """FR-018 (amended 2026-10-20): the /compact step reports 0 tokens; compact_boundary carries its input."""
    lines = [
        {
            "ts": "t1",
            "event": {"type": "system", "subtype": "compact_boundary", "compact_metadata": {"pre_tokens": 36150}},
        },
        {"ts": "t2", "event": {"type": "result", "result": "", "usage": {"input_tokens": 0, "output_tokens": 0}}},
        {
            "ts": "t3",
            "event": {"type": "system", "subtype": "compact_boundary", "compact_metadata": {"pre_tokens": 100}},
        },
        {"ts": "t4", "event": {"type": "system", "subtype": "compact_boundary"}},  # no metadata: counts as 0
        {"ts": "t5", "event": {"type": "result", "result": "ok", "usage": {"input_tokens": 7, "output_tokens": 3}}},
    ]
    summary = records.summarise(lines)
    assert summary.compaction_tokens_estimate == 36250 and summary.compactions == ["t1", "t3", "t4"]
    assert summary.compaction_estimates_missing == 1  # the boundary without metadata
    assert summary.tokens == {"input": 7, "cache_write": 0, "cache_read": 0, "output": 3}


def test_receipts_carry_the_compaction_estimate_from_the_stream(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub = load("stub_agent")
    receipts = _stub_run(tmp_path / "runs", monkeypatch, "calibration", ["memkernel"], ("demo-retain", "demo-compact"))
    assert all(records.validate_receipt(r) == [] and r["schema_version"] == 3 for r in receipts)
    by_task = {r["task_id"]: r for r in receipts if r["stage"] == "evaluation"}
    compact = by_task["demo-compact"]
    assert len(compact["stages"]["compactions"]) == 1
    assert compact["compaction_tokens_estimate"] == stub.COMPACT_PRE_TOKENS
    assert all(r["compaction_tokens_estimate"] == 0 for r in receipts if r["task_id"] == "demo-retain")
    assert all(r["compaction_estimates_missing"] == 0 for r in receipts)


def test_calibration_report_sets_the_compaction_estimate_beside_the_receipts_never_into_them() -> None:
    def session(arm: str, index: int, group: str, estimate: int, compactions: int) -> dict[str, Any]:
        return _trial(
            arm,
            "t9",
            index,
            phase="calibration",
            group=group,
            outcome=None,
            checker_passed=None,
            tokens={"input": 10, "cache_write": 100, "cache_read": 1000, "output": 5},
            compaction_tokens_estimate=estimate,
            stages={"exposure_at": None, "evaluation_at": None, "compactions": ["c"] * compactions},
        )

    receipts = [
        session("memkernel", 0, "lc-compact", 36000, 1),
        session("memkernel", 1, "lc-retain", 0, 0),
        session("bare", 0, "lc-compact", 0, 0),  # an lc-compact session without its compaction
    ]
    text = report.render(receipts, PARAMS)
    assert "Tokens: input 30, cache write 300, cache read 3000, output 15" in text  # the estimate is not in them
    assert "summaries' output is not recorded): 36000" in text
    assert "`lc-compact` sessions with exactly one compaction: 1 of 2" in text
    assert "| memkernel | 2220 | 36000 | 38220 |" in text and "| bare | 1110 | 0 | 1110 |" in text


@pytest.mark.parametrize("pre_tokens", ["36150", -5, True, 1.5, None])
def test_a_malformed_pre_tokens_counts_as_missing_instead_of_failing_the_summary(pre_tokens: object) -> None:
    event = {"type": "system", "subtype": "compact_boundary", "compact_metadata": {"pre_tokens": pre_tokens}}
    summary = records.summarise([{"ts": "t1", "event": event}])
    assert summary.compactions == ["t1"] and summary.compaction_tokens_estimate == 0
    assert summary.compaction_estimates_missing == 1


def _session(
    phase: str, chain: str, group: str, estimate: int, compactions: int, missing: int = 0, run: str = "r"
) -> dict[str, Any]:
    return _trial(
        "memkernel",
        chain,
        0,
        run_id=run,
        phase=phase,
        group=group,
        outcome=None if phase == "calibration" else "passed",
        checker_passed=None if phase == "calibration" else True,
        compaction_tokens_estimate=estimate,
        compaction_estimates_missing=missing,
        stages={"exposure_at": None, "evaluation_at": None, "compactions": ["c"] * compactions},
    )


@pytest.mark.parametrize("phase", ["calibration", "measured"])
def test_a_compaction_without_an_estimate_is_flagged_even_beside_a_valid_one(phase: str) -> None:
    """Review of #41: one compaction with pre_tokens and one without must not pass as a complete estimate."""
    receipts = [
        _session(phase, "t1", "lc-compact", 36000, 1),
        _session(phase, "t2", "lc-compact", 36000, 2, missing=1),  # one valid, one missing, in one session
    ]
    text = report.render(receipts, PARAMS)
    assert "WARNING: 1 compaction(s) in 1 session(s) recorded no estimate" in text
    warning = text.split("WARNING")[1].splitlines()[0]
    assert "r t2.memkernel.r0 position 0 (1)" in warning and "t1.memkernel.r0" not in warning
    assert "WARNING" not in report.render([_session(phase, "t1", "lc-compact", 36000, 1)], PARAMS)


@pytest.mark.parametrize("phase", ["calibration", "measured"])
def test_the_report_does_not_depend_on_the_order_of_the_receipts(phase: str) -> None:
    receipts = [
        _session(phase, "t2", "lc-compact", 0, 1, missing=1, run="r2"),
        _session(phase, "t1", "lc-compact", 0, 1, missing=1, run="r1"),
        _session(phase, "t1", "lc-compact", 0, 1, missing=1, run="r2"),
    ]
    text = report.render(receipts, PARAMS)
    assert text == report.render(list(reversed(receipts)), PARAMS)
    warning = text.split("WARNING")[1].splitlines()[0]
    assert warning.index("r1 t1.memkernel.r0") < warning.index("r2 t1.memkernel.r0") < warning.index("r2 t2")


def test_the_measured_report_sets_the_compaction_estimate_beside_the_receipts_too() -> None:
    """FR-018: the measured run's lc-compact sessions undercount the same way as calibration's."""
    receipts = [_session("measured", "t1", "lc-compact", 36000, 1), _session("measured", "t2", "lc-retain", 0, 0)]
    text = report.render(receipts, PARAMS)
    measured = text.split("## Token usage (measured)")[1].split("## Label")[0]
    assert "summaries' output is not recorded): 36000" in measured
    assert "| memkernel | 2 | 36000 | 36002 |" in measured  # receipts, the estimate, the two together


@pytest.mark.parametrize(
    ("event", "failed"),
    [
        ({"type": "assistant", "error": "authentication_failed", "message": {"content": []}}, True),
        ({"type": "result", "is_error": True, "api_error_status": 401, "result": "Invalid API key"}, True),
        ({"type": "result", "is_error": True, "api_error_status": 403, "result": "Forbidden"}, True),
        ({"type": "result", "is_error": True, "api_error_status": 529, "result": "Overloaded"}, False),
        ({"type": "result", "is_error": True, "api_error_status": 429, "result": "Rate limited"}, False),
        ({"type": "result", "is_error": False, "result": "done", "usage": {}}, False),
    ],
)
def test_an_authentication_failure_is_recognised_from_the_stream(event: dict[str, Any], failed: bool) -> None:
    """Task 18c: the recalibration's discarded attempt failed with "Invalid API key" (401, authentication_failed)."""
    assert records.summarise([{"ts": "t", "event": event}]).authentication_failed is failed


def test_a_session_whose_key_is_refused_is_invalid_not_a_failure_of_the_arm(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FR-015a (c): the API refused the run's key; the receipt must not count as a valid trial of the arm."""
    import sys as _sys

    agent = tmp_path / "refused_agent.py"
    agent.write_text(
        "import json\n"
        "for event in (\n"
        "    {'type': 'system', 'subtype': 'init', 'session_id': 's', 'mcp_servers': []},\n"
        "    {'type': 'assistant', 'error': 'authentication_failed',\n"
        "     'message': {'content': [{'type': 'text', 'text': 'Invalid API key'}]}},\n"
        "    {'type': 'result', 'subtype': 'success', 'is_error': True, 'api_error_status': 401,\n"
        "     'terminal_reason': 'api_error', 'result': 'Invalid API key', 'usage': {}},\n"
        "):\n"
        "    print(json.dumps(event), flush=True)\n",
        encoding="utf-8",
    )
    root = tmp_path / "runs"
    root.mkdir()
    cfg = runner.RunConfig(
        run_root=root,
        run_id="measured",
        phase="measured",
        model="stub",
        code_sha="c",
        preregistration_sha256="p",
        agent_cmd=(_sys.executable, str(agent)),
        memkernel_cmd="stub",
        memkernel_python=_sys.executable,
        tasks_root=runner.SUITE_DIR / "fixtures" / "demo-tasks",
        oracles_root=runner.SUITE_DIR / "fixtures" / "demo-oracles",
        timeout_s=60.0,
    )
    monkeypatch.setattr(runner, "_inside_checkout", lambda path: False)
    path = runner.run(cfg, ["demo-retain"], ["bare"], runs=1)
    receipts = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert len(receipts) == 1  # the chain stops at the invalid session
    receipt = receipts[0]
    assert receipt["valid"] is False and receipt["invalid_reason"] == "authentication_failed"
    assert receipt["outcome"] is None and records.validate_receipt(receipt) == []
    # one refused call, two error events: the assistant message and the result (FR-018: events, not calls)
    assert receipt["api_errors"] == {"401": 1, "authentication_failed": 1}


def test_a_key_refused_after_the_agent_has_acted_still_makes_the_session_invalid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FR-015a (c), amended 2026-10-23: a revoked key is a failure of the environment at any step, not of the arm."""
    import sys as _sys

    calls = tmp_path / "calls"
    agent = tmp_path / "revoked_agent.py"
    agent.write_text(
        "import json, pathlib\n"
        f"calls = pathlib.Path({str(calls)!r})\n"
        "n = int(calls.read_text()) if calls.exists() else 0\n"
        "calls.write_text(str(n + 1))\n"
        "events = [{'type': 'system', 'subtype': 'init', 'session_id': 's', 'mcp_servers': []}]\n"
        "if n == 0:  # the first session works\n"
        "    events.append({'type': 'result', 'subtype': 'success', 'is_error': False, 'result': 'ok',\n"
        "                   'usage': {'input_tokens': 5, 'output_tokens': 1}})\n"
        "else:  # then the key is revoked\n"
        "    events.append({'type': 'result', 'subtype': 'success', 'is_error': True, 'api_error_status': 401,\n"
        "                   'result': 'Invalid API key', 'usage': {}})\n"
        "for event in events:\n"
        "    print(json.dumps(event), flush=True)\n",
        encoding="utf-8",
    )
    root = tmp_path / "runs"
    root.mkdir()
    cfg = runner.RunConfig(
        run_root=root,
        run_id="measured",
        phase="measured",
        model="stub",
        code_sha="c",
        preregistration_sha256="p",
        agent_cmd=(_sys.executable, str(agent)),
        memkernel_cmd="stub",
        memkernel_python=_sys.executable,
        tasks_root=runner.SUITE_DIR / "fixtures" / "demo-tasks",
        oracles_root=runner.SUITE_DIR / "fixtures" / "demo-oracles",
        timeout_s=60.0,
    )
    monkeypatch.setattr(runner, "_inside_checkout", lambda path: False)
    path = runner.run(cfg, ["demo-retain"], ["bare"], runs=1)
    first, second = (json.loads(line) for line in path.read_text(encoding="utf-8").splitlines())
    assert first["valid"] is True and first["position"] == 0
    assert second["valid"] is False and second["invalid_reason"] == "authentication_failed"
    trial = report.assemble([first, second])[0]
    assert trial.valid is False and trial.invalid_reason == "authentication_failed"  # the pair is removed


def _v2_calibration_receipt(**overrides: Any) -> dict[str, Any]:
    receipt = {k: v for k, v in _receipt(schema_version=2, phase="calibration").items() if k != "api_errors"}
    receipt.update(overrides)
    return receipt


def test_the_report_accepts_version_2_receipts_for_calibration_only() -> None:
    """FR-018 (amended 2026-10-24): the committed calibration receipts predate api_errors and stay as they are."""
    assert records.validate_report_receipt(_v2_calibration_receipt()) == []
    assert records.validate_report_receipt(_receipt()) == []
    refused = records.validate_report_receipt(_v2_calibration_receipt(phase="measured"))
    assert refused and "calibration only" in refused[0]
    # a version-2 receipt that carries the newer field is not what version 2 was
    assert any(
        "unexpected key api_errors" in e
        for e in records.validate_report_receipt(_v2_calibration_receipt(api_errors={}))
    )


def test_the_committed_calibration_receipts_are_accepted_by_the_report() -> None:
    path = records.SCHEMA_PATH.parent / "calibration" / "receipts-20261024T033046Z.jsonl"
    receipts = records.read_receipts(path)
    assert len(receipts) == 50
    assert all(records.validate_report_receipt(r) == [] for r in receipts)


@pytest.mark.parametrize(
    ("events", "expected"),
    [
        ([], {}),
        ([{"type": "result", "is_error": False, "result": "done", "usage": {}}], {}),
        (  # the discarded 2026-10-22 attempt: each refused call is an assistant message and a result
            [
                {"type": "assistant", "error": "authentication_failed", "message": {"content": []}},
                {"type": "result", "is_error": True, "api_error_status": 401, "result": "Invalid API key"},
            ],
            {"authentication_failed": 1, "401": 1},
        ),
        ([{"type": "result", "is_error": True, "api_error_status": 529, "result": "Overloaded"}] * 2, {"529": 2}),
        ([{"type": "result", "is_error": True, "result": "?"}], {"none": 1}),  # an error with no status
        # the agent's own failures, not the API's: scored, never counted, so never a truncating tail (review of 18d)
        ([{"type": "result", "subtype": "error_max_turns", "is_error": True, "result": ""}], {}),
        ([{"type": "result", "subtype": "error_during_execution", "is_error": True, "result": ""}], {}),
        (
            [{"type": "result", "subtype": "success", "is_error": True, "result": "API Error: Connection error"}],
            {"none": 1},
        ),
        ([{"type": "assistant", "error": None, "message": {"content": []}}], {"none": 1}),
        ([{"type": "assistant", "message": {"content": []}}], {}),
    ],
)
def test_api_errors_count_error_events_by_key(events: list[dict[str, Any]], expected: dict[str, int]) -> None:
    summary = records.summarise([{"ts": "t", "event": e} for e in events])
    assert summary.api_errors == expected


# The analysis plan (FR-016, amended 2026-10-24), truncation (FR-015a) and API errors (FR-018) in the report.

POOLED = {**PARAMS, "min_pairs_inferential": 20, "min_tasks_inferential": 16}


def _pooled(outcomes: dict[str, list[str]], tasks: int = 20, runs: int = 1) -> list[dict[str, Any]]:
    """One receipt per (arm, task, run); ``outcomes[arm][task index]`` is that arm's outcome on every run."""
    receipts = []
    for arm, per_task in outcomes.items():
        for t in range(tasks):
            for run in range(runs):
                outcome = per_task[t]
                receipts.append(_trial(arm, f"t{t:02d}", run, outcome=outcome, checker_passed=outcome == "passed"))
    return receipts


def _endpoint(text: str) -> str:
    return text.split("## Primary endpoint (all tasks pooled)", 1)[1].split("\n## ", 1)[0]


def test_sign_test_and_holm_match_hand_computed_values() -> None:
    assert report.sign_test(9, 1) == pytest.approx(22 / 1024)  # 9 to 1 of 10 non-tied tasks: decisive
    assert report.sign_test(8, 2) == pytest.approx(112 / 1024)  # 8 to 2: not
    assert report.sign_test(5, 0) == pytest.approx(0.0625)  # the best a five-task group can do
    assert report.sign_test(15, 5) == pytest.approx(0.04138946533203125)
    assert report.sign_test(0, 0) == 1.0
    assert report.holm({"a": 0.01, "b": 0.04}) == pytest.approx({"a": 0.02, "b": 0.04})
    assert report.holm({"a": 0.03, "b": 0.02}) == pytest.approx({"b": 0.04, "a": 0.04})  # monotone


def test_the_bootstrap_is_seeded_and_weights_tasks_equally() -> None:
    effects = [100.0, 0.0, 0.0, -100.0, 50.0]
    first = report.bootstrap_interval(effects, 2000, 17)
    assert first == report.bootstrap_interval(effects, 2000, 17)
    assert first[0] <= sum(effects) / len(effects) <= first[1]
    assert report.bootstrap_interval([0.0] * 5, 2000, 17) == (0.0, 0.0)
    # a task with many runs counts once: three runs of t00 against one of t01 give a mean of the two task effects
    trials = report.assemble(
        [_trial("memkernel", "t00", r) for r in range(3)]
        + [_trial("claude_md", "t00", r, outcome="failed", checker_passed=False) for r in range(3)]
        + [_trial("memkernel", "t01", 0, outcome="failed", checker_passed=False), _trial("claude_md", "t01", 0)]
    )
    effects_by_task, pairs = report.task_effects(trials, "claude_md")
    assert effects_by_task == {"t00": 1.0, "t01": -1.0} and pairs == 4


def test_a_gain_against_both_comparators_is_the_only_headline_gain() -> None:
    passed, failed = ["passed"] * 20, ["failed"] * 20
    text = report.render(_pooled({"memkernel": passed, "claude_md": failed, "fs_grep": failed}), POOLED)
    endpoint = _endpoint(text)
    assert "| claude_md | 20 | 20 | 20 | 0 | 0 | 0.0000 | 0.0000 | +100.0 |" in endpoint
    assert endpoint.count("| gain |") == 2 and "**Headline:** gain against every primary comparator" in endpoint
    assert "Inferential: every primary comparison has at least 20 valid pairs covering at least 16 tasks" in text

    one_side = report.render(_pooled({"memkernel": passed, "claude_md": failed, "fs_grep": passed}), POOLED)
    assert "| gain |" in _endpoint(one_side) and "**Headline:** no gain claimed" in one_side

    loss = report.render(_pooled({"memkernel": failed, "claude_md": passed, "fs_grep": passed}), POOLED)
    assert _endpoint(loss).count("| loss |") == 2


def test_equivalence_needs_the_whole_interval_inside_the_band() -> None:
    passed = ["passed"] * 20
    tied = report.render(_pooled({"memkernel": passed, "claude_md": passed, "fs_grep": passed}), POOLED)
    endpoint = _endpoint(tied)
    assert "| claude_md | 20 | 20 | 0 | 0 | 20 | 1.0000 | 1.0000 | +0.0 | +0.0 to +0.0 | equivalent |" in endpoint

    # 3 tasks each way: not significant, a mean of 0, but an interval wider than +/-10 points
    mixed = ["passed"] * 3 + ["failed"] * 3 + ["passed"] * 14
    flipped = ["failed"] * 3 + ["passed"] * 3 + ["passed"] * 14
    text = report.render(_pooled({"memkernel": mixed, "claude_md": flipped, "fs_grep": flipped}), POOLED)
    assert "| claude_md | 20 | 20 | 3 | 3 | 14 |" in _endpoint(text)  # ties are left out of the test, and counted
    assert _endpoint(text).count("| no detectable difference |") == 2


def test_below_the_minimum_no_label_is_applied() -> None:
    passed, failed = ["passed"] * 20, ["failed"] * 20
    text = report.render(_pooled({"memkernel": passed, "claude_md": failed, "fs_grep": failed}), PARAMS)  # 30 pairs
    assert _endpoint(text).count("| not applied (descriptive) |") == 2
    assert "**Headline:** no claim (descriptive" in text and "Descriptive: at least one primary comparison" in text
    few_tasks = {**POOLED, "min_pairs_inferential": 1, "min_tasks_inferential": 21}
    assert "not applied (descriptive)" in report.render(
        _pooled({"memkernel": passed, "claude_md": failed, "fs_grep": failed}), few_tasks
    )


def _timed(arm: str, task: str, minute: int, errors: dict[str, int] | None = None, **kw: Any) -> dict[str, Any]:
    return _trial(arm, task, 0, started_at=f"2026-11-01T10:{minute:02d}:00.000Z", api_errors=errors or {}, **kw)


def test_a_strict_tail_of_api_errors_truncates_the_run() -> None:
    receipts = [
        _timed("claude_md", "t1", 0),  # ran before the tail: its pair is removed all the same
        _timed("fs_grep", "t1", 1),
        _timed("memkernel", "t2", 2),
        _timed("claude_md", "t2", 3),
        _timed("memkernel", "t1", 4, {"529": 1}, outcome="failed", checker_passed=False),
        _timed("fs_grep", "t2", 5, {"none": 1}, outcome="failed", checker_passed=False),
    ]
    tail = report.truncated_sessions(receipts)
    assert [(r["arm"], r["task_id"]) for r in tail] == [("memkernel", "t1"), ("fs_grep", "t2")]
    text = report.render(receipts, PARAMS)
    assert "| memkernel | 2 | 1 | 1/1 (100%) | 0 | 0 | 0 | none | 1 |" in text  # truncated: neither invalid nor scored
    assert "| claude_md (primary) | 1 | 1 | 0 | 0 | 0 | 0 | 1 | +0.0 |" in text  # t1's pair truncated, t2's scored
    assert "**Truncated:** 2 session(s)" in text and "- r memkernel t1 run 0 position 0" in text


def test_errors_that_are_not_a_tail_stay_scored_and_counted() -> None:
    receipts = [
        _timed("memkernel", "t1", 0, {"529": 1}, outcome="failed", checker_passed=False),  # a burst, then recovery
        _timed("claude_md", "t1", 1),
        _timed(
            "memkernel",
            "t2",
            2,
            {"401": 1, "authentication_failed": 1},
            valid=False,
            invalid_reason="authentication_failed",
            outcome=None,
            checker_passed=None,
        ),  # not a truncating key
    ]
    assert report.truncated_sessions(receipts) == []
    text = report.render(receipts, PARAMS)
    assert "| claude_md (primary) | 1 | 0 | 0 | 1 | 0 | 0 | 0 | -100.0 |" in text  # t1 scored, a memkernel failure
    assert "| memkernel | 401: 1, 529: 1, authentication_failed: 1 |" in text
    assert "Counts are error events, not failed calls" in text and "- Truncation: none." in text


def test_calibration_api_errors_are_unknown_for_version_2_receipts() -> None:
    old = _v2_calibration_receipt()
    new = _receipt(phase="calibration", api_errors={"529": 2})
    text = report.render([old, new], PARAMS)
    assert (
        "- API error events: unknown for 1 session(s) (schema version 2 receipts do not record them); "
        "in the other 1: 529: 2" in text
    )
    assert "- API error events: none" in report.render([_receipt(phase="calibration")], PARAMS)
    only_old = report.render([old], PARAMS)
    assert "(schema version 2 receipts do not record them)\n" in only_old


def test_the_report_cli_rejects_a_version_2_measured_receipt(tmp_path: Path) -> None:
    receipts, params = tmp_path / "r.jsonl", tmp_path / "p.json"
    params.write_text(json.dumps(PARAMS), encoding="utf-8")
    receipts.write_text(json.dumps(_v2_calibration_receipt(phase="measured")) + "\n", encoding="utf-8")
    assert report.main(["--receipts", str(receipts), "--params", str(params)]) == 1
    receipts.write_text(json.dumps(_v2_calibration_receipt()) + "\n", encoding="utf-8")
    assert report.main(["--receipts", str(receipts), "--params", str(params)]) == 0


def test_the_estimate_reads_one_parameter_block_and_each_arms_groups() -> None:
    estimate = load("estimate")
    with pytest.raises(ValueError, match="exactly one"):
        estimate.load_parameters("# no block\n")
    with pytest.raises(ValueError, match="exactly one"):
        estimate.load_parameters("```json\n{}\n```\n```json\n{}\n```\n")
    with pytest.raises(ValueError, match="lack: model"):
        estimate.load_parameters("```json\n{}\n```\n")
    assert estimate.task_group("lc-compact-port") == "lc-compact" and estimate.task_group("lc-wiki-slugs") == "lc-wiki"
    with pytest.raises(ValueError, match="no lifecycle group"):
        estimate.task_group("demo-retain")
    assert estimate.arm_groups("wiki_studio") == ("lc-wiki",)
    assert estimate.arm_groups("memkernel") == estimate.GROUPS
    # a group the calibration never ran cannot be estimated, so it is refused rather than costed at 0
    receipts = [_receipt(group="lc-retain", run_id="c", chain_id="x")]
    parameters = {
        "prices_usd_per_mtok": {"input": 1, "cache_write": 1, "cache_read": 1, "output": 1},
        "runs_per_arm_per_task": 1,
        "tasks": ["lc-wiki-slugs"],
        "arms": ["memkernel"],
        "invalid_allowance": 0,
    }
    with pytest.raises(ValueError, match="no lc-wiki chain"):
        estimate.estimate(parameters, receipts)
    parameters["tasks"] = ["lc-retain-rounding"]
    assert estimate.estimate(parameters, receipts)["total_usd"] == pytest.approx(2 / 1_000_000)


def test_the_bootstrap_draws_only_through_random_so_every_python_gives_the_same_interval() -> None:
    """SC-8: the published interval must reproduce byte for byte; these values are the same on 3.11 and 3.13."""
    assert report.bootstrap_interval([100.0, 0.0, 0.0, -100.0, 50.0, 25.0, -50.0], 1000, 17) == (
        -39.285714285714285,
        50.0,
    )
    assert report.bootstrap_interval([100.0, 0.0, 50.0], 7, 3) == (16.666666666666668, 83.33333333333333)


ANALYSIS = {key: POOLED[key] for key in report.PREREGISTERED}
REPORT_ONLY = {**{k: v for k, v in POOLED.items() if k not in report.PREREGISTERED}, "code_sha": "c"}  # as _receipt
PREREGISTERED_TASKS = [f"t{t:02d}" for t in range(20)] + ["t1"]


def _preregistration(tmp_path: Path, **changes: Any) -> Path:
    path = tmp_path / "preregistration.md"
    block = {
        **ANALYSIS,
        **changes,
        "tasks": PREREGISTERED_TASKS,
        "runs_per_arm_per_task": 1,
        "prices_usd_per_mtok": {"input": 2, "cache_write": 2.5, "cache_read": 0.1, "output": 10},
        "prices_as_of": "x",
        "invalid_allowance": 0,
        "calibration_receipts": "x",
        "spend_limit_usd": 1,
    }
    path.write_text(f"# Preregistration\n\n```json\n{json.dumps(block)}\n```\n", encoding="utf-8")
    return path


def _cli(
    tmp_path: Path,
    receipts: list[dict[str, Any]],
    params: dict[str, Any],
    prereg: Path | None,
    capsys: pytest.CaptureFixture[str],
) -> tuple[int, str, str]:
    receipts_path, params_path = tmp_path / "r.jsonl", tmp_path / "p.json"
    receipts_path.write_text("".join(json.dumps(r) + "\n" for r in receipts), encoding="utf-8")
    params_path.write_text(json.dumps(params), encoding="utf-8")
    argv = ["--receipts", str(receipts_path), "--params", str(params_path)]
    status = report.main(argv + (["--preregistration", str(prereg)] if prereg else []))
    out, err = capsys.readouterr()
    return status, out, err


def test_the_report_takes_its_analysis_from_the_preregistration(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Review of 18d: the band, the bootstrap, alpha and the minimums are the preregistered ones, not --params'."""
    prereg = _preregistration(tmp_path)
    digest = records.sha256_bytes(prereg.read_bytes())
    passed = ["passed"] * 20
    receipts = [
        {**r, "preregistration_sha256": digest}
        for r in _pooled({"memkernel": passed, "claude_md": passed, "fs_grep": passed})
    ]
    status, text, _ = _cli(tmp_path, receipts, REPORT_ONLY, prereg, capsys)
    assert status == 0 and _endpoint(text).count("| equivalent |") == 2 and "seed 17" in text

    narrower = _preregistration(tmp_path, bootstrap_seed=5, min_tasks_inferential=21)  # a changed block
    digest = records.sha256_bytes(narrower.read_bytes())
    receipts = [{**r, "preregistration_sha256": digest} for r in receipts]
    status, changed, _ = _cli(tmp_path, receipts, REPORT_ONLY, narrower, capsys)
    assert status == 0 and "seed 5" in changed and "not applied (descriptive)" in changed


@pytest.mark.parametrize(
    ("case", "message"),
    [
        ("no-preregistration", "measured receipts need --preregistration"),
        ("other-sha", "not this file's"),
        ("params-disagree", "--params disagrees with the preregistration on: no_gain_band_points"),
        ("missing-key", "lack: bootstrap_seed"),
    ],
)
def test_the_report_refuses_an_analysis_that_is_not_the_preregistered_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], case: str, message: str
) -> None:
    prereg = _preregistration(tmp_path)
    digest = "0" * 64 if case == "other-sha" else records.sha256_bytes(prereg.read_bytes())
    if case == "missing-key":
        text = prereg.read_text(encoding="utf-8").replace('"bootstrap_seed": 17, ', "")
        prereg.write_text(text, encoding="utf-8")
        digest = records.sha256_bytes(prereg.read_bytes())
    params = {**REPORT_ONLY, "no_gain_band_points": 5} if case == "params-disagree" else REPORT_ONLY
    receipts = [_trial("memkernel", "t1", 0, preregistration_sha256=digest)]
    status, _, err = _cli(tmp_path, receipts, params, None if case == "no-preregistration" else prereg, capsys)
    assert status == 1 and message in err


def test_a_significant_test_with_a_zero_mean_is_neither_gain_nor_loss() -> None:
    """Review of 18d: 16 tasks at +0.25 and 4 at -1 give a mean of exactly 0 and Holm p 0.0236; FR-016 labels a
    gain or a loss only by the mean's sign, so this falls to the interval rule."""
    receipts = []
    for t in range(20):
        for run in range(4):
            if t < 16:  # memkernel passes every run; the comparators pass three of four
                mk, other = "passed", "failed" if run == 0 else "passed"
            else:  # memkernel fails every run; the comparators pass every run
                mk, other = "failed", "passed"
            receipts.append(_trial("memkernel", f"t{t:02d}", run, outcome=mk, checker_passed=mk == "passed"))
            for arm in ("claude_md", "fs_grep"):
                receipts.append(_trial(arm, f"t{t:02d}", run, outcome=other, checker_passed=other == "passed"))
    endpoint = _endpoint(report.render(receipts, POOLED))
    assert "| claude_md | 20 | 80 | 16 | 4 | 0 | 0.0118 | 0.0236 | +0.0 |" in endpoint
    assert "| loss |" not in endpoint and "| gain |" not in endpoint
    assert endpoint.count("| no detectable difference (the test's direction and the mean's sign disagree) |") == 2


def test_each_primary_comparison_carries_the_inferential_label_on_its_own() -> None:
    """Review of 18d: 20 valid pairs against claude_md and 19 against fs_grep; only fs_grep is descriptive."""
    passed, failed = ["passed"] * 20, ["failed"] * 20
    receipts = _pooled({"memkernel": passed, "claude_md": failed, "fs_grep": failed})
    receipts = [r for r in receipts if not (r["arm"] == "fs_grep" and r["task_id"] == "t19")]
    text = report.render(receipts, {**POOLED, "min_tasks_inferential": 19})
    endpoint = _endpoint(text)
    assert "| claude_md | 20 | 20 |" in endpoint and endpoint.split("| claude_md |")[1].split("\n")[0].endswith(
        "| gain |"
    )
    assert endpoint.split("| fs_grep |")[1].split("\n")[0].endswith("| not applied (descriptive) |")
    assert "**Headline:** no gain claimed" in endpoint  # conservative: a gain needs every comparator
    assert "Descriptive: at least one primary comparison" in text


@pytest.mark.parametrize(
    ("change", "field"),
    [
        ({"invalid_allowance": float("nan")}, "invalid_allowance"),
        ({"spend_limit_usd": float("inf")}, "spend_limit_usd"),
        ({"runs_per_arm_per_task": 0}, "runs_per_arm_per_task"),
        (
            {"prices_usd_per_mtok": {"input": -1, "cache_write": 1, "cache_read": 1, "output": 1}},
            "prices_usd_per_mtok.input",
        ),
        ({"prices_usd_per_mtok": {"input": 1, "cache_write": 1, "cache_read": 1}}, "prices_usd_per_mtok.output"),
    ],
)
def test_the_estimate_refuses_parameters_that_are_not_finite_positive_numbers(
    change: dict[str, Any], field: str
) -> None:
    """Review of 18d: invalid_allowance NaN printed $nan as within the limit and started the run."""
    estimate = load("estimate")
    parameters = {key: 1 for key in estimate.REQUIRED}
    parameters["prices_usd_per_mtok"] = {"input": 1, "cache_write": 1, "cache_read": 1, "output": 1}
    parameters.update(change)
    with pytest.raises(ValueError, match=field.replace(".", "\\.")):
        estimate.load_parameters(f"```json\n{json.dumps(parameters)}\n```\n")


def test_a_mean_that_is_exactly_zero_is_zero_however_the_effects_add_up() -> None:
    """Review of 18d: over five runs, fifteen task effects of +1/5, three of -1 and two ties sum to exactly 0, but
    floating-point addition left a positive residue that labelled both comparisons gain. Effects are exact."""
    receipts = []
    for t in range(20):
        for run in range(5):
            if t < 15:  # memkernel passes every run; the comparators fail one of five
                mk, other = "passed", "failed" if run == 0 else "passed"
            elif t < 18:  # memkernel fails every run; the comparators pass every run
                mk, other = "failed", "passed"
            else:  # ties
                mk = other = "passed"
            receipts.append(_trial("memkernel", f"t{t:02d}", run, outcome=mk, checker_passed=mk == "passed"))
            for arm in ("claude_md", "fs_grep"):
                receipts.append(_trial(arm, f"t{t:02d}", run, outcome=other, checker_passed=other == "passed"))
    effects, pairs = report.task_effects(report.assemble(receipts), "claude_md")
    assert sum(effects.values()) == 0 and pairs == 100
    text = report.render(receipts, POOLED)
    endpoint = _endpoint(text)
    assert "| claude_md | 20 | 100 | 15 | 3 | 2 |" in endpoint and "| 0.0151 |" in endpoint
    assert "| gain |" not in endpoint and "| loss |" not in endpoint
    assert "the test's direction and the mean's sign disagree" in endpoint
    assert "**Headline:** no gain claimed" in endpoint


def test_an_interval_on_the_band_edge_is_inside_it() -> None:
    """Exact effects: every task at +1/10 is a mean and interval of exactly +10 points, inside a +/-10 band."""
    receipts = []
    for t in range(20):
        for run in range(10):
            mk, other = "passed", "failed" if run == 0 else "passed"
            receipts.append(_trial("memkernel", f"t{t:02d}", run, outcome=mk, checker_passed=True))
            for arm in ("claude_md", "fs_grep"):
                receipts.append(_trial(arm, f"t{t:02d}", run, outcome=other, checker_passed=other == "passed"))
    lenient = {**POOLED, "alpha": 0.0}  # no test can reject, so the interval rule decides
    assert _endpoint(report.render(receipts, lenient)).count("| +10.0 to +10.0 | equivalent |") == 2


def test_a_rejecting_test_whose_direction_and_mean_disagree_is_not_a_loss() -> None:
    """Review of 18d (FR-016, second amendment of 2026-10-24): 16 tasks at +1/5 and 4 at -1 reject in memkernel's
    favour (16 to 4, Holm p 0.0236) with a mean of -0.04; the old rule called that a loss."""
    receipts = []
    for t in range(20):
        for run in range(5):
            if t < 16:  # memkernel passes every run; the comparators fail one of five
                mk, other = "passed", "failed" if run == 0 else "passed"
            else:  # memkernel fails every run; the comparators pass every run
                mk, other = "failed", "passed"
            receipts.append(_trial("memkernel", f"t{t:02d}", run, outcome=mk, checker_passed=mk == "passed"))
            for arm in ("claude_md", "fs_grep"):
                receipts.append(_trial(arm, f"t{t:02d}", run, outcome=other, checker_passed=other == "passed"))
    endpoint = _endpoint(report.render(receipts, POOLED))
    assert "| claude_md | 20 | 100 | 16 | 4 | 0 | 0.0118 | 0.0236 | -4.0 |" in endpoint
    assert "| loss |" not in endpoint and "| gain |" not in endpoint
    assert endpoint.count("| no detectable difference (the test's direction and the mean's sign disagree) |") == 2


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"model": "another-model"}, "model another-model"),
        ({"code_sha": "other"}, "code_sha other"),
        ({"task_id": "unregistered"}, "task unregistered"),
        ({"run_index": 1}, "run_index 1"),  # the block preregisters one run per arm per task
    ],
)
def test_the_report_refuses_receipts_outside_the_preregistered_experiment(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], change: dict[str, Any], message: str
) -> None:
    """Review of #50: receipts naming the right preregistration but another model, code, task or run were counted
    as the preregistered experiment and could produce a gain headline."""
    prereg = _preregistration(tmp_path)
    digest = records.sha256_bytes(prereg.read_bytes())
    receipts = [
        _trial("memkernel", "t1", 0, preregistration_sha256=digest),
        _trial("claude_md", "t1", 0, preregistration_sha256=digest),
    ]
    status, _, _ = _cli(tmp_path, receipts, REPORT_ONLY, prereg, capsys)
    assert status == 0
    receipts[0] = {**receipts[0], **change}
    status, out, err = _cli(tmp_path, receipts, REPORT_ONLY, prereg, capsys)
    assert status == 1 and "outside the preregistered experiment" in err and message in err and out == ""


def test_scored_sessions_with_api_errors_are_counted_by_arm_not_only_events() -> None:
    """Review of #50 (FR-015a): one session with two 529s and two sessions with one each differ in sessions."""
    one = [_timed("memkernel", "t1", 0, {"529": 2}), _timed("memkernel", "t2", 1), _timed("claude_md", "t1", 2)]
    two = [
        _timed("memkernel", "t1", 0, {"529": 1}),
        _timed("memkernel", "t2", 1, {"529": 1}),
        _timed("claude_md", "t1", 2),
    ]
    assert "| memkernel | 529: 2 | 1 |" in report.render(one, PARAMS)
    assert "| memkernel | 529: 2 | 2 |" in report.render(two, PARAMS)
    # a truncated session is listed with the tail, not counted as a scored session with errors
    tail = [_timed("claude_md", "t1", 0), _timed("memkernel", "t1", 1, {"529": 1})]
    assert "| memkernel | 529: 1 | 0 |" in report.render(tail, PARAMS)


def test_sessions_of_excluded_trials_are_not_counted_as_scored_error_sessions() -> None:
    """Review of #50: the count must follow the trial, not the session."""
    invalid = [  # a 529 alongside the refusal that invalidated the trial
        _timed(
            "memkernel",
            "t1",
            0,
            {"529": 1, "401": 1},
            valid=False,
            invalid_reason="authentication_failed",
            outcome=None,
            checker_passed=None,
        ),
        _timed("claude_md", "t1", 1),
    ]
    assert "| memkernel | 401: 1, 529: 1 | 0 |" in report.render(invalid, PARAMS)

    def chained(position: int, minute: int, errors: dict[str, int]) -> dict[str, Any]:
        return _trial(
            "memkernel",
            "t1",
            0,
            chain_length=2,
            position=position,
            stage="exposure" if position == 0 else "evaluation",
            started_at=f"2026-11-01T10:{minute:02d}:00.000Z",
            api_errors=errors,
        )

    # an early error session whose trial a later truncated session excludes
    cut_later = [chained(0, 0, {"529": 1}), _timed("claude_md", "t1", 1), chained(1, 2, {"529": 1})]
    text = report.render(cut_later, PARAMS)
    assert "| memkernel | 529: 2 | 0 |" in text and "**Truncated:** 1 session(s)" in text


def test_the_report_refuses_an_arm_the_preregistration_omits(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    prereg = _preregistration(tmp_path, arms=["bare", "placebo", "protocol", "claude_md", "memkernel"])
    digest = records.sha256_bytes(prereg.read_bytes())
    receipts = [_trial("fs_grep", "t1", 0, preregistration_sha256=digest)]
    status, _, err = _cli(tmp_path, receipts, REPORT_ONLY, prereg, capsys)
    assert status == 1 and "arm fs_grep" in err

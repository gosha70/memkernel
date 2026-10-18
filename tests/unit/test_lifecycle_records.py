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
        "schema_version": 1,
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


def _stub_run(root: Path, monkeypatch: pytest.MonkeyPatch, phase: str, arms: list[str]) -> list[dict[str, Any]]:
    """One demo-retain chain per arm through the real runner with the stub agent, in ``phase``."""
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
    path = runner.run(cfg, ["demo-retain"], arms, runs=1)
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


@pytest.mark.parametrize(("output", "accepted"), [("0.4.0", True), ("0.3.1", False), (None, False)])
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

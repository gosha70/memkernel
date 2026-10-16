# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""The credential-free demonstration (FR-014, SC-4): passes as frozen, fails when a rule is broken."""

from __future__ import annotations

import dataclasses

import pytest

from tests.unit._lifecycle_suite import load

pytestmark = pytest.mark.unit

runner = load("runner")


def test_demo_passes_with_the_frozen_rules(capsys: pytest.CaptureFixture[str]) -> None:
    assert runner.demo() == 0
    assert "0 failure(s)" in capsys.readouterr().out


def test_demo_detects_an_arm_that_carries_more_than_its_rule(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """End to end: make the runner leak the workspace for `bare`; the demo must fail on exactly that."""
    real_prepare = runner.prepare_session

    def leaky_prepare(task: object, arm: object, *args: object) -> object:
        if arm.name == "bare":  # type: ignore[attr-defined]
            arm = dataclasses.replace(arm, persist_workspace=True)  # type: ignore[call-overload]
        return real_prepare(task, arm, *args)

    monkeypatch.setattr(runner, "prepare_session", leaky_prepare)

    assert runner.demo() == 1
    out = capsys.readouterr().out
    assert "FAIL bare: workspace carry-over True != rule False" in out
    assert out.count("FAIL ") == 1


def test_demo_detects_missing_compaction_hooks() -> None:
    receipts = [
        {
            "task_id": "demo-compact",
            "arm": "memkernel",
            "valid": True,
            "invalid_reason": None,
            "hooks": [{"event": "SessionStart", "exit_status": 0, "ts": "t"}],
            "stage": "evaluation",
            "outcome": "passed",
            "chain_id": "c",
        }
    ]
    full = {
        (task, arm, 1): {
            "workspace_note": arm == "claude_md",
            "transcripts": arm == "fs_grep",
            "store_marker": arm == "memkernel" and task == "demo-retain",
            "wiki_page": True,
        }
        for task in ("demo-retain", "demo-wiki")
        for arm in runner.ARM_NAMES
    }
    failures = runner.check_demo(full, receipts)
    assert any("hook events not recorded" in f for f in failures)

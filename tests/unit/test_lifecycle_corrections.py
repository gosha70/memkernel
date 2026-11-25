# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""The lc-correct group and its runner changes (specs/memkernel-0-16-lifecycle-corrections), without a model.

The governed arms' curators, memkernel's correction path and the gate check against a real store and wiki-studio
are in tests/integration/test_lifecycle_corrections_governed.py.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import sys
from collections import Counter
from typing import TYPE_CHECKING

import pytest

from tests.unit._lifecycle_suite import SUITE_DIR, load

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit

runner = load("runner")
report = load("report")
correct_checker = load("correct_checker")
corrections = load("corrections")

TASKS_ROOT = SUITE_DIR / "tasks"
ORACLES_ROOT = SUITE_DIR / "oracles"
CORRECT_IDS = sorted(p.name for p in TASKS_ROOT.iterdir() if p.name.startswith("lc-correct-"))
D2_ARMS = ("memkernel", "memkernel_governed", "memkernel_governed_oracle", "fs_grep", "claude_md", "bare")
EIGHT = ("deploy-window", "token-lifetime", "cache-invalidation", "retry-policy", "backup-retention",
         "access-review", "flag-cleanup", "invoice-rounding")  # fmt: skip


def _task(task_id: str) -> object:
    return runner.load_task(TASKS_ROOT / task_id)


def _spec(task_id: str) -> dict[str, object]:
    spec: dict[str, object] = json.loads((TASKS_ROOT / task_id / "task.json").read_text(encoding="utf-8"))
    return spec


# ── the task set (FR-001, D1, D4, D7) ─────────────────────────


def test_twelve_chains_include_the_eight_of_issue_90_and_split_six_six_by_kind() -> None:
    assert len(CORRECT_IDS) == 12
    assert {f"lc-correct-{slug}" for slug in EIGHT} <= set(CORRECT_IDS)
    kinds = Counter(_spec(t)["correction"]["kind"] for t in CORRECT_IDS)  # type: ignore[index]
    assert kinds == {"replacement": 6, "withdrawal": 6}


@pytest.mark.parametrize("task_id", CORRECT_IDS)
def test_each_fixture_wiki_has_a_competing_page_with_the_obsolete_rule_and_is_governed(task_id: str) -> None:
    obsolete = json.loads((ORACLES_ROOT / task_id / "answers.json").read_text(encoding="utf-8"))["obsolete"]
    wiki = TASKS_ROOT / task_id / "tree" / "knowledge" / "wiki"
    pages = [p for p in wiki.rglob("*.md") if p.name not in ("index.md", "log.md")]
    assert any(re.search(o, p.read_text(encoding="utf-8"), re.IGNORECASE) for p in pages for o in obsolete)
    assert len(pages) >= 2, "a competing page and a distractor"
    policy = json.loads((wiki / ".wiki-studio.json").read_text(encoding="utf-8"))["policy"]
    assert policy["approval_required"] is True and policy["approver_required"] is True  # #90 section 3.4


@pytest.mark.parametrize("task_id", CORRECT_IDS)
def test_the_evaluation_prompt_names_neither_the_correction_nor_its_value(task_id: str) -> None:
    spec = _spec(task_id)
    prompt = spec["sessions"][-1]["steps"][-1]["prompt"].lower()  # type: ignore[index]
    correction = spec["correction"]
    assert "correct" not in prompt and "new rule" not in prompt and "updated rule" not in prompt
    for term in spec["fact_terms"]:  # type: ignore[attr-defined]
        assert term.lower() not in prompt
    assert correction["headline"].lower() not in prompt  # type: ignore[index]
    assert "answer.md" in prompt


# ── the checker (FR-001) ──────────────────────────────────────


def _answer(tmp_path: Path, text: str) -> Path:
    (tmp_path / "ANSWER.md").write_text(text, encoding="utf-8")
    return tmp_path


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("No; the earliest is Monday at 09:00 UTC.", "informed"),
        ("It can go out on Friday after 17:00 UTC.", "obsolete"),
        ("It used to be Friday after 17:00, now it is Monday.", "informed"),  # names both, says which holds
        ("Friday or Monday.", "informed"),  # the stated limit: both values without saying which holds pass
        ("Ask the release manager.", "other"),
    ],
)
def test_the_checker_has_three_outcomes(tmp_path: Path, text: str, expected: str) -> None:
    oracle = ORACLES_ROOT / "lc-correct-deploy-window"
    assert correct_checker.classify(_answer(tmp_path, text), oracle) == expected
    assert correct_checker.check(tmp_path, oracle) == (expected == "informed", expected)


def test_a_missing_or_linked_answer_is_other(tmp_path: Path) -> None:
    oracle = ORACLES_ROOT / "lc-correct-deploy-window"
    assert correct_checker.classify(tmp_path, oracle) == "other"
    outside = tmp_path.parent / "outside.md"
    outside.write_text("Monday", encoding="utf-8")
    (tmp_path / "ANSWER.md").symlink_to(outside)
    assert correct_checker.classify(tmp_path, oracle) == "other"


# ── the exposure copy never carries the correction (FR-002, SC-2) ─


@pytest.mark.parametrize("task_id", CORRECT_IDS)
@pytest.mark.parametrize("arm_name", [*D2_ARMS, "informed"])
def test_the_exposure_copy_carries_session_zero_and_never_the_correction(
    task_id: str, arm_name: str, tmp_path: Path
) -> None:
    task = _task(task_id)
    arm = runner.load_arm(arm_name)
    session_zero = tmp_path / "s0-workspace"
    shutil.copytree(task.tree, session_zero)  # type: ignore[attr-defined]
    page = session_zero / "knowledge" / "wiki" / "decisions" / "recorded.md"
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text("recorded in session 0\n", encoding="utf-8")
    chain = tmp_path / "chain"
    chain.mkdir()
    dirs = runner.prepare_session(task, arm, 1, chain, runner.ChainState(workspace=session_zero))
    copied = dirs.workspace / "knowledge" / "wiki" / "decisions" / "recorded.md"
    assert copied.is_file(), "the exposure state reaches the next session for every arm"
    text = "\n".join(p.read_text(encoding="utf-8") for p in dirs.workspace.rglob("*") if p.is_file()).lower()
    for term in _spec(task_id)["fact_terms"]:  # type: ignore[attr-defined]
        assert term.lower() not in text
    assert _spec(task_id)["correction"]["headline"].lower() not in text  # type: ignore[index]


# ── phases and calibration (FR-003, decision B3) ──────────────


def _cfg(tmp_path: Path, phase: str) -> object:
    return runner.RunConfig(
        run_root=tmp_path / "runs",
        run_id="t",
        phase=phase,
        model="stub",
        code_sha="t",
        preregistration_sha256=None,
        agent_cmd=(sys.executable, str(SUITE_DIR / "stub_agent.py")),
        memkernel_cmd="stub-memkernel",
        memkernel_python=sys.executable,
        tasks_root=SUITE_DIR / "fixtures" / "demo-tasks",
        oracles_root=SUITE_DIR / "fixtures" / "demo-oracles",
        timeout_s=60.0,
        hook_command_override=(sys.executable, "-c", "import sys; sys.stdin.read()"),
        ops_command=(sys.executable, str(SUITE_DIR / "stub_ops.py")),
    )


def test_an_lc_correct_calibration_refuses_any_arm_but_bare_and_informed(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="runs only bare, informed"):
        runner.run(_cfg(tmp_path, "calibration"), ["demo-correct"], ["bare", "memkernel"], runs=1)


def test_the_informed_reference_never_runs_in_a_measured_run(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="informed runs only in calibration"):
        runner.run(_cfg(tmp_path, "measured"), ["demo-correct"], ["informed"], runs=1)


def test_an_lc_correct_calibration_is_graded_with_three_outcomes(tmp_path: Path) -> None:
    receipts_path = runner.run(_cfg(tmp_path, "calibration"), ["demo-correct"], ["bare", "informed"], runs=1)
    receipts = [json.loads(line) for line in receipts_path.read_text(encoding="utf-8").splitlines()]
    final = [r for r in receipts if r["stage"] == "evaluation"]
    assert {r["arm"] for r in final} == {"bare", "informed"}
    assert all(r["valid"] and r["outcome"] in ("passed", "failed") and r["answer_class"] for r in final)
    corrected = {r["arm"]: r["correction"] for r in final}
    assert corrected["bare"] == {"path": "none", "delivered": False}
    assert corrected["informed"] == {"path": "instruction_brief", "delivered": True}


def test_the_informed_instruction_carries_the_brief_only_after_the_correction(tmp_path: Path) -> None:
    task = runner.load_task(SUITE_DIR / "fixtures" / "demo-tasks" / "demo-correct")
    arm = runner.load_arm("informed")
    dirs = runner.SessionDirs(tmp_path, tmp_path, tmp_path, tmp_path, None, None, "primary")
    assert runner._instruction_file(arm, dirs, task.brief_for(0)) is None
    path = runner._instruction_file(arm, dirs, task.brief_for(1))
    assert path is not None and "DEMO-Y" in path.read_text(encoding="utf-8")


def test_a_failed_correction_makes_the_session_invalid_not_a_failure_of_the_arm(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path, "demo")
    cfg.ops_command = (sys.executable, "-c", "import sys; sys.exit(3)")  # type: ignore[attr-defined]
    receipts_path = runner.run(cfg, ["demo-correct"], ["memkernel"], runs=1)
    receipts = [json.loads(line) for line in receipts_path.read_text(encoding="utf-8").splitlines()]
    (final,) = [r for r in receipts if r["position"] == 1]
    assert final["valid"] is False and final["invalid_reason"] == "correction_failed"
    assert final["correction"]["delivered"] is False and "exited 3" in final["correction"]["error"]


# ── the arms (FR-004, D2, D3) ─────────────────────────────────


@pytest.mark.parametrize("arm_name", ["memkernel_governed", "memkernel_governed_oracle"])
def test_the_governed_arms_pin_their_curator_policy_and_extend_the_memkernel_block(arm_name: str) -> None:
    arm_dir = SUITE_DIR / "arms" / arm_name
    config = json.loads((arm_dir / "config.frozen.json").read_text(encoding="utf-8"))
    policy = (arm_dir / config["curator_policy"]).read_bytes()
    assert hashlib.sha256(policy).hexdigest() == config["curator_policy_sha256"]
    block = (SUITE_DIR / "arms" / "memkernel" / "instruction.md").read_bytes()
    assert (arm_dir / "instruction.md").read_bytes().startswith(block)
    mode = {"curator_scripted": "scripted", "curator_oracle": "oracle"}[corrections.PATHS[arm_name]]
    assert config["curator"] == mode
    arm = runner.load_arm(arm_name)
    assert arm.wiki_governed and arm.persist_store and arm.groups == ("lc-correct",)
    assert arm.carry == ("doc_internal/proposals",) and arm.cli_pin is not None


def test_the_informed_reference_is_calibration_only_and_runs_on_lc_correct_only() -> None:
    arm = runner.load_arm("informed")
    assert arm.phases == ("calibration",) and arm.groups == ("lc-correct",)
    assert not (arm.persist_store or arm.persist_workspace or arm.persist_transcripts or arm.mcp)


def test_every_arm_has_a_correction_path() -> None:
    assert set(corrections.PATHS) == set(runner.ARM_NAMES)


def test_claude_md_gets_the_brief_appended_and_fs_grep_a_note(tmp_path: Path) -> None:
    correction = _spec("lc-correct-deploy-window")["correction"]
    (tmp_path / "CLAUDE.md").write_text("# Notes\n", encoding="utf-8")
    assert corrections.deliver("claude_md", correction, tmp_path, None, None, None)["delivered"]
    text = (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")
    assert text.startswith("# Notes\n") and "Monday at 09:00 UTC" in text
    memory = tmp_path / "memory"
    memory.mkdir()
    corrections.deliver("fs_grep", correction, tmp_path, memory, None, None)
    assert "Monday at 09:00 UTC" in (memory / corrections.GREP_NOTE_FILE).read_text(encoding="utf-8")
    assert corrections.deliver("bare", correction, tmp_path, None, None, None) == {"path": "none", "delivered": False}


# ── the report (FR-005, SC-4) ─────────────────────────────────


def _receipt(arm: str, task_id: str, group: str, answer: str | None, tokens: int, gate: object = None) -> dict:  # type: ignore[type-arg]
    return {
        "run_id": "r",
        "chain_id": f"{task_id}.{arm}.r0",
        "position": 0,
        "stage": "evaluation",
        "task_id": task_id,
        "group": group,
        "arm": arm,
        "run_index": 0,
        "valid": True,
        "invalid_reason": None,
        "outcome": "passed" if answer == "informed" else "failed",
        "tokens": {"input": tokens, "cache_write": 0, "cache_read": 0, "output": 1},
        "answer_class": answer,
        "gate": gate,
        "started_at": "2026-11-25T00:00:00Z",
    }


def test_the_report_tables_lc_correct_by_answer_class_and_tokens_by_group() -> None:
    receipts = [
        _receipt("bare", "lc-correct-a", "lc-correct", "obsolete", 10),
        _receipt("memkernel", "lc-correct-a", "lc-correct", "informed", 30),
        _receipt("memkernel_governed", "lc-correct-a", "lc-correct", "informed", 50, {"breaches": [{"page": "x"}]}),
        _receipt("bare", "lc-wiki-a", "lc-wiki", None, 7),
    ]
    trials = report.assemble(receipts)
    arms = ["bare", "memkernel", "memkernel_governed"]
    table = "\n".join(report._correct_table(trials, arms))
    assert "| bare | 1 | 1 | 0 | 1/1 (100%) | 0 | 0 | - |" in table
    assert "| memkernel_governed | 1 | 1 | 1 | 0/1 (0%) | 0 | 0 | 1 |" in table
    pairs = "\n".join(report._correct_pairs(trials, arms))
    assert "| memkernel | 1 | 0 | 1 | 0 | 0 | 0 |" in pairs
    tokens = "\n".join(report._tokens_by_group(trials))
    assert "| lc-correct | memkernel | 1 | 30 | 0 | 0 | 1 |" in tokens
    assert "| lc-wiki | bare | 1 | 7 | 0 | 0 | 1 |" in tokens


# ── qualifying the chains from their calibration (FR-003) ─────

qualify = load("qualify")


def _calibration(task_id: str, arm: str, answer: str | None, valid: bool = True, run: int = 0) -> dict:  # type: ignore[type-arg]
    return {
        "group": "lc-correct",
        "phase": "calibration",
        "stage": "evaluation",
        "chain_id": f"{task_id}.{arm}.r{run}",
        "task_id": task_id,
        "arm": arm,
        "valid": valid,
        "outcome": "passed" if answer == "informed" else "failed",
        "answer_class": answer,
    }


def test_a_chain_qualifies_only_when_bare_always_misses_and_informed_always_answers() -> None:
    receipts = [
        _calibration("ok", "bare", "obsolete"),
        _calibration("ok", "bare", "other", run=1),
        _calibration("ok", "informed", "informed"),
        _calibration("guessed", "bare", "informed"),  # at ceiling: bare reaches Y
        _calibration("guessed", "informed", "informed"),
        _calibration("broken", "bare", "obsolete"),
        _calibration("broken", "informed", "other"),  # a prompt the informed reference cannot answer
        _calibration("unrun", "bare", None, valid=False),
        _calibration("unrun", "informed", "informed"),
    ]
    result = qualify.qualify(receipts)
    assert result["qualified"] == ["ok"]
    reasons = {d["task_id"]: d["reason"] for d in result["dropped"]}
    assert reasons == {
        "broken": "informed missed the corrected rule in 1 of 1",
        "guessed": "bare answered the corrected rule in 1 of 1",
        "unrun": "no valid bare trial",
    }
    assert "Qualified: 1 of 4 chains." in qualify.render(result)


def test_a_measured_arm_in_the_calibration_receipts_is_refused() -> None:
    with pytest.raises(ValueError, match="no place in an lc-correct calibration"):
        qualify.qualify([_calibration("ok", "memkernel", "informed")])

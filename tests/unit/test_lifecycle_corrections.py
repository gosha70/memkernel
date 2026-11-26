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
from pathlib import Path

import pytest

from tests.unit._lifecycle_suite import SUITE_DIR, load

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
    obsolete = _spec(task_id)["correction"]["obsolete_patterns"]  # type: ignore[index]  # what the curator matches
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


# ── the checker (FR-001, amendment A1: only the answer line is graded) ─


def _answer(tmp_path: Path, text: str) -> Path:
    (tmp_path / "ANSWER.md").write_text(text, encoding="utf-8")
    return tmp_path


@pytest.mark.parametrize(
    ("task_id", "text", "expected"),
    [
        ("lc-correct-deploy-window", "Answer: Monday; 09:00 UTC\n\nThe window closed Thursday.", "informed"),
        ("lc-correct-deploy-window", "**Answer:** Monday; 9:00 UTC", "informed"),  # markdown, an unpadded hour
        ("lc-correct-deploy-window", "Answer: Friday; 17:00 UTC", "obsolete"),
        ("lc-correct-deploy-window", "Answer: Thursday; 16:00 UTC", "obsolete"),
        ("lc-correct-deploy-window", "Answer: Monday; 17:00 UTC", "other"),  # half right is not right
        ("lc-correct-deploy-window", "Answer: Friday or Monday; 09:00 UTC", "other"),  # two weekdays: unparsable
        # the review's counterexamples: a value in prose decides nothing, only the answer line does
        ("lc-correct-deploy-window", "Monday is explicitly not allowed.", "other"),
        ("lc-correct-email-logging", "Do not log the internal user ID; log the email hash.", "other"),
        ("lc-correct-email-logging", "Answer: yes; email hash\n\nDo not log the internal user ID.", "obsolete"),
        ("lc-correct-rate-limit", "The limit is not 120; all 300 requests are accepted.", "other"),
        ("lc-correct-rate-limit", "Answer: 300\n\nThe limit is not 120.", "obsolete"),
        # completeness: every part of a multi-part answer must hold
        ("lc-correct-token-lifetime", "Answer: 15 minutes; 24 hours", "other"),
        ("lc-correct-token-lifetime", "Answer: 15 minutes", "other"),
        ("lc-correct-token-lifetime", "Answer: 15 min; 8 h", "informed"),
        ("lc-correct-review-approvals", "Answer: no; 1", "other"),
        ("lc-correct-review-approvals", "Answer: yes; 2", "obsolete"),
    ],
)
def test_the_checker_grades_the_answer_line_with_three_outcomes(
    tmp_path: Path, task_id: str, text: str, expected: str
) -> None:
    oracle = ORACLES_ROOT / task_id
    assert correct_checker.classify(_answer(tmp_path, text), oracle) == expected
    assert correct_checker.check(tmp_path, oracle) == (expected == "informed", expected)


def test_a_missing_or_linked_answer_is_other(tmp_path: Path) -> None:
    oracle = ORACLES_ROOT / "lc-correct-deploy-window"
    assert correct_checker.classify(tmp_path, oracle) == "other"
    outside = tmp_path.parent / "outside.md"
    outside.write_text("Answer: Monday; 09:00 UTC", encoding="utf-8")
    (tmp_path / "ANSWER.md").symlink_to(outside)
    assert correct_checker.classify(tmp_path, oracle) == "other"


@pytest.mark.parametrize("task_id", CORRECT_IDS)
def test_every_reference_including_the_adversarial_ones_grades_as_declared(task_id: str, tmp_path: Path) -> None:
    import importlib.util

    references = sorted((TASKS_ROOT / task_id / "reference").glob("*.py"))
    names = {r.stem for r in references}
    assert {"naive", "informed", "both", "adv_prose_only", "adv_line_x_prose_y", "adv_extra_parts"} <= names
    for path in references:
        spec = importlib.util.spec_from_file_location(f"ref_{task_id}_{path.stem}".replace("-", "_"), path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        workdir = tmp_path / path.stem
        workdir.mkdir()
        module.apply(workdir)
        assert correct_checker.classify(workdir, ORACLES_ROOT / task_id) == module.EXPECTED, path.stem


@pytest.mark.parametrize("task_id", CORRECT_IDS)
def test_the_answer_form_in_the_prompt_reveals_no_fact_term(task_id: str) -> None:
    spec = _spec(task_id)
    form = json.loads((ORACLES_ROOT / task_id / "answers.json").read_text(encoding="utf-8"))["form"]
    prompt = spec["sessions"][-1]["steps"][-1]["prompt"]  # type: ignore[index]
    assert f"`Answer: {form}`" in prompt
    for term in spec["fact_terms"]:  # type: ignore[attr-defined]
        assert term.lower() not in form.lower()


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


def test_an_lc_correct_calibration_is_graded_with_three_outcomes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(runner, "require_isolated_image", lambda cfg: None)  # the stub agent needs no image
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
    assert "| bare | 1 | 1 | 0 | 1/1 (100%) | 0 | 0 | 0 | - | - |" in table
    assert "| memkernel_governed | 1 | 1 | 1 | 0/1 (0%) | 0 | 0 | 0 | 1 | 0 |" in table
    pairs = "\n".join(report._correct_pairs(trials, arms))
    assert "| memkernel | 1 | 0 | 1 | 0 | 0 | 0 | 0 |" in pairs
    tokens = "\n".join(report._tokens_by_group(trials))
    assert "| lc-correct | memkernel | 1 | 30 | 0 | 0 | 1 |" in tokens
    assert "| lc-wiki | bare | 1 | 7 | 0 | 0 | 1 |" in tokens


# ── qualifying the chains from their calibration (FR-003) ─────

qualify = load("qualify")


def _calibration(
    task_id: str, arm: str, answer: str | None, valid: bool = True, run: int = 0, position: int = 1
) -> dict:  # type: ignore[type-arg]
    return {
        "group": "lc-correct",
        "phase": "calibration",
        "stage": "evaluation" if position == 1 else "exposure",
        "position": position,
        "chain_id": f"{task_id}.{arm}.r{run}",
        "task_id": task_id,
        "arm": arm,
        "valid": valid,
        "outcome": "passed" if answer == "informed" else "failed",
        "answer_class": answer,
    }


def _complete(answers: dict[tuple[str, str], list[str | None]]) -> list[dict]:  # type: ignore[type-arg]
    receipts = []
    for (task, arm), per_run in answers.items():
        for run, answer in enumerate(per_run):
            receipts.append(_calibration(task, arm, None, run=run, position=0))
            receipts.append(_calibration(task, arm, answer, run=run))
    return receipts


def test_a_chain_qualifies_only_when_bare_always_misses_and_informed_always_answers() -> None:
    receipts = _complete(
        {
            ("ok", "bare"): ["obsolete", "other"],
            ("ok", "informed"): ["informed", "informed"],
            ("guessed", "bare"): ["informed", "obsolete"],  # at ceiling: bare reaches Y
            ("guessed", "informed"): ["informed", "informed"],
            ("broken", "bare"): ["obsolete", "obsolete"],
            ("broken", "informed"): ["other", "informed"],  # a prompt the informed reference cannot answer
        }
    )
    result = qualify.qualify(receipts, ["broken", "guessed", "ok"], runs=2)
    assert result["qualified"] == ["ok"]
    reasons = {d["task_id"]: d["reason"] for d in result["dropped"]}
    assert reasons == {
        "broken": "informed missed the corrected rule in 1 of 2",
        "guessed": "bare answered the corrected rule in 1 of 2",
    }
    assert "Qualified: 1 of 3 chains." in qualify.render(result)


def test_a_chain_that_stopped_at_an_invalid_exposure_is_an_invalid_trial() -> None:
    receipts = [
        *_complete({("t", "informed"): ["informed"]}),
        _calibration("t", "bare", None, valid=False, position=0),  # the chain ends at its invalid exposure
    ]
    result = qualify.qualify(receipts, ["t"], runs=1)
    assert result["qualified"] == [] and result["dropped"] == [{"task_id": "t", "reason": "no valid bare trial"}]
    assert result["chains"][0]["invalid"] == 1


@pytest.mark.parametrize(
    ("receipts", "message"),
    [
        (_complete({("a", "bare"): ["obsolete"], ("a", "informed"): ["informed"]}), "2 chain\\(s\\) missing"),
        (
            _complete({("a", "bare"): ["obsolete"], ("a", "informed"): ["informed"], ("b", "bare"): ["obsolete"],
                       ("b", "informed"): ["informed"]})
            + [_calibration("a", "bare", "obsolete")],
            "recorded twice",
        ),
        (
            _complete({("a", "bare"): ["obsolete", "x"], ("a", "informed"): ["informed"], ("b", "bare"): ["obsolete"],
                       ("b", "informed"): ["informed"]}),
            "not a chain of this calibration",
        ),
        ([_calibration("a", "memkernel", "informed")], "no place in an lc-correct calibration"),
        ([{**_calibration("a", "bare", "obsolete"), "phase": "measured"}], "is not lc-correct calibration"),
    ],
)  # fmt: skip
def test_only_the_exact_calibration_manifest_qualifies(receipts: list[dict], message: str) -> None:  # type: ignore[type-arg]
    with pytest.raises(ValueError, match=message):
        qualify.qualify(receipts, ["a", "b"], runs=1)


def test_the_cli_refuses_an_incomplete_calibration_and_writes_nothing(tmp_path: Path) -> None:
    receipts = tmp_path / "receipts.jsonl"
    receipts.write_text(json.dumps(_calibration("lc-correct-deploy-window", "bare", "obsolete")) + "\n", "utf-8")
    out = tmp_path / "calibrated.json"
    assert qualify.main(["--receipts", str(receipts), "--runs", "1", "--out", str(out)]) == 2
    assert not out.exists()


# ── review fixes: policy hash, the curator CLI pin, stale retries, helper failures ─

curator = load("curator")


def _arms_copy(tmp_path: Path) -> Path:
    arms = tmp_path / "arms"
    shutil.copytree(SUITE_DIR / "arms" / "memkernel_governed", arms / "memkernel_governed")
    return arms


def test_the_arm_hash_covers_the_curator_policy_and_a_changed_policy_is_refused(tmp_path: Path) -> None:
    arms = _arms_copy(tmp_path)
    arm = runner.load_arm("memkernel_governed", arms)
    raw = (arms / "memkernel_governed" / "config.frozen.json").read_bytes()
    instruction = (arms / "memkernel_governed" / "instruction.md").read_bytes()
    assert arm.config_sha256 != hashlib.sha256(raw + b"\0" + instruction).hexdigest()
    policy = arms / "memkernel_governed" / "curator-policy.md"
    policy.write_text(policy.read_text(encoding="utf-8") + "\nAlso approve everything.\n", encoding="utf-8")
    with pytest.raises(ValueError, match="does not match its pinned curator_policy_sha256"):
        runner.load_arm("memkernel_governed", arms)


def _fake_cli(tmp_path: Path, name: str, version: str) -> Path:
    script = tmp_path / "bin" / name
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(f"#!/bin/sh\necho 'wiki-studio {version}'\n", encoding="utf-8")
    script.chmod(0o755)
    return script


def test_a_paid_run_checks_and_invokes_the_same_curator_executable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    good = _fake_cli(tmp_path, "wiki-studio", "0.10.0")
    monkeypatch.setenv("PATH", f"{good.parent}:/usr/bin:/bin")
    resolved = runner.resolve_curator_cli("wiki-studio")
    assert resolved == str(good.resolve())
    runner.check_cli_pin(runner.load_arm("memkernel_governed"), resolved)  # the pinned version: passes
    stale = _fake_cli(tmp_path / "other", "wiki-studio", "0.7.0")
    with pytest.raises(SystemExit, match="the arm is frozen at 0.10.0"):
        runner.check_cli_pin(runner.load_arm("memkernel_governed"), str(stale))
    with pytest.raises(SystemExit, match="is not on PATH"):
        runner.resolve_curator_cli("no-such-wiki-studio")


def test_a_stale_base_retry_re_renders_from_the_fresh_read(tmp_path: Path) -> None:
    proposed: list[str] = []
    reads = iter([("FIRST READ", "sha-1"), ("FRESH READ", "sha-2")])

    def cli(verb: str, *args: str) -> tuple[int, str]:
        if verb == "read":
            content, sha = next(reads)
            return 0, json.dumps({"content": content, "sha256": sha})
        if verb == "propose":
            source = Path(args[args.index("--from") + 1])
            proposed.append((source / "decisions" / "p.md").read_text(encoding="utf-8"))
            proposed.append(json.loads((source / ".base.json").read_text(encoding="utf-8"))["decisions/p.md"])
            return (9, "stale base") if len(proposed) == 2 else (0, "")
        return 0, ""

    first = curator.read_page(cli, "decisions/p.md")
    refusal = curator._land(cli, "decisions/p.md", lambda content: f"corrected({content})", first, "t")
    assert refusal is None
    assert proposed == ["corrected(FIRST READ)", "sha-1", "corrected(FRESH READ)", "sha-2"]


def test_an_unreadable_wiki_studio_answer_is_a_failed_correction_not_a_crash(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    page = workspace / "knowledge" / "wiki" / "decisions" / "d.md"
    page.parent.mkdir(parents=True)
    page.write_text(
        "---\npage_type: decision\nstatus: draft\nmemkernel_ref: mem-1\n---\nDeploys on Fridays.\n", encoding="utf-8"
    )
    correction = _spec("lc-correct-deploy-window")["correction"]

    def ops(command: str, *args: str) -> dict:  # type: ignore[type-arg]
        return {"live": True} if command == "exists" else {"import_error": None}

    def cli(verb: str, *args: str) -> tuple[int, str]:
        return 0, "not json"

    with pytest.raises(corrections.CorrectionError, match="answered unreadably"):
        corrections.deliver("memkernel_governed", correction, workspace, None, ops, cli)


def test_a_helper_that_hangs_makes_the_session_invalid(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runner, "HELPER_TIMEOUT_S", 0.5)
    cfg = _cfg(tmp_path, "demo")
    cfg.ops_command = (sys.executable, "-c", "import time; time.sleep(30)")  # type: ignore[attr-defined]
    receipts_path = runner.run(cfg, ["demo-correct"], ["memkernel"], runs=1)
    receipts = [json.loads(line) for line in receipts_path.read_text(encoding="utf-8").splitlines()]
    (final,) = [r for r in receipts if r["position"] == 1]
    assert final["invalid_reason"] == "correction_failed" and "did not finish" in final["correction"]["error"]


def test_the_report_keeps_truncated_trials_apart_and_their_gate_evidence() -> None:
    base = _receipt("memkernel_governed", "lc-correct-a", "lc-correct", "informed", 5, {"breaches": [{"page": "x"}]})
    truncated = {**base, "chain_id": "lc-correct-b.memkernel_governed.r0", "task_id": "lc-correct-b"}
    missing = {**base, "chain_id": "lc-correct-c.memkernel_governed.r0", "task_id": "lc-correct-c", "gate": None}
    trials = report.assemble([base, truncated, missing], truncated=[truncated])
    table = "\n".join(report._correct_table(trials, ["memkernel_governed"]))
    assert "| memkernel_governed | 3 | 2 | 2 | 0/2 (0%) | 0 | 0 | 1 | 2 | 1 |" in table


# ── blinding (the #90 review): what the agent can reach from its session ─


def test_the_probe_check_flags_every_way_out() -> None:
    leak = {
        "cwd": "/runs/demo/demo-correct.bare.r0/s1/workspace",
        "sessions": ["s0", "s1"],
        "run_dir": ["demo-correct.bare.r0", "receipts.jsonl"],
        "s0_reachable": True,
        "oracles": ["lc-correct-deploy-window"],
    }
    failures = runner.check_probes({"bare": leak}, separated=True)
    assert len(failures) == 5, failures
    clean = {
        "cwd": "/runs/demo/sessions/0a1b2c3d4e5f/workspace",
        "sessions": ["0a1b2c3d4e5f"],
        "run_dir": "unreadable (13)",
        "s0_reachable": False,
        "oracles": "unreadable (13)",
    }
    assert runner.check_probes({"bare": clean}, separated=True) == []


def test_without_staging_the_probe_would_see_the_chain(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runner, "stage_session", lambda dirs, cfg: dirs)  # the layout before the review
    runner.run(_cfg(tmp_path, "demo"), ["demo-correct"], ["bare"], runs=1)
    probe = json.loads(
        (tmp_path / "runs" / "t" / "demo-correct.bare.r0" / "s1" / "workspace" / "PROBE.json").read_text()
    )
    failures = runner.check_probes({"bare": probe}, separated=False)
    assert any("names the task" in f for f in failures) and any("../../s0" in f for f in failures)


def test_a_run_with_an_agent_user_keeps_the_run_chains_and_receipts_the_harnesss(tmp_path: Path) -> None:
    import os
    import stat

    cfg = _cfg(tmp_path, "demo")
    cfg.agent_uid, cfg.agent_gid = os.getuid(), os.getgid()  # type: ignore[attr-defined]  # chown to oneself: the path runs
    receipts_path = runner.run(cfg, ["demo-correct"], ["bare"], runs=1)
    run_dir = receipts_path.parent
    mode = lambda path: stat.S_IMODE(path.stat().st_mode)  # noqa: E731
    assert mode(run_dir) == 0o711 and mode(run_dir / "sessions") == 0o711
    assert mode(run_dir / "demo-correct.bare.r0") == 0o700 and mode(receipts_path) == 0o600
    assert mode(run_dir / "demo-correct.bare.r0" / "s1") == 0o700
    assert list((run_dir / "sessions").iterdir()) == []  # every session moved back into its chain
    probe = json.loads((run_dir / "demo-correct.bare.r0" / "s1" / "workspace" / "PROBE.json").read_text())
    assert runner.check_probes({"bare": probe}, separated=False) == []


# ── second DeepSeek round on the review fixes ─────────────────


@pytest.mark.parametrize(
    ("task_id", "text"),
    [
        ("lc-correct-token-lifetime", "Answer: 2 fortnights, 15 minutes; 8 hours"),  # an unknown unit is not skipped
        ("lc-correct-token-lifetime", "Answer: 15 minuets; 8 hours"),
        ("lc-correct-token-lifetime", "Answer: 15; 8 hours"),  # a number without a unit
        ("lc-correct-deploy-window", "Answer: Monday; 25:99 UTC"),  # not a time of day
    ],
)
def test_a_part_with_a_number_the_checker_cannot_read_is_other(tmp_path: Path, task_id: str, text: str) -> None:
    assert correct_checker.classify(_answer(tmp_path, text), ORACLES_ROOT / task_id) == "other"


memkernel_ops = load("memkernel_ops")


def test_a_hand_edited_proposal_needs_its_curator_delta(tmp_path: Path) -> None:
    archive = tmp_path / ".audit" / "proposals" / "p"
    archive.mkdir(parents=True)
    (archive / "plan.json").write_text("{}", encoding="utf-8")
    (archive / "proposal.md").write_text("p", encoding="utf-8")
    receipt = {
        "proposal": "p",
        "plan_sha256": hashlib.sha256(b"{}").hexdigest(),
        "submission_manifest": [
            {"path": ".ingest-snapshot/preview/decisions/d.md", "sha256": "a" * 64},
            {"path": "preview/decisions/d.md", "sha256": "a" * 64},
        ],
    }
    assert memkernel_ops._archived(tmp_path, receipt)  # promoted as staged: no delta needed
    receipt["submission_manifest"][1]["sha256"] = "b" * 64  # the curator edited the staged page
    assert not memkernel_ops._archived(tmp_path, receipt)
    (archive / "curator-delta.md").write_text("delta", encoding="utf-8")
    assert memkernel_ops._archived(tmp_path, receipt)
    (archive / "plan.json").write_text('{"x": 1}', encoding="utf-8")  # no longer the plan the receipt names
    assert not memkernel_ops._archived(tmp_path, receipt)


def test_in_the_image_only_an_explicit_unreadable_passes_the_probe() -> None:
    probe = {
        "cwd": "/runs/r/sessions/abc/workspace",
        "sessions": ["abc"],
        "run_dir": None,
        "s0_reachable": False,
        "oracles": "permission check skipped",
    }
    failures = runner.check_probes({"bare": probe}, separated=True)
    assert len(failures) == 2 and runner.check_probes({"bare": probe}, separated=False) == []


def test_an_agent_user_without_root_is_refused_before_the_run(tmp_path: Path) -> None:
    import os

    if os.geteuid() == 0:
        pytest.skip("as root the harness can hand sessions to any user")
    cfg = _cfg(tmp_path, "demo")
    cfg.agent_uid = os.geteuid() + 1  # type: ignore[attr-defined]
    with pytest.raises(SystemExit, match="needs the harness to run as root"):
        runner.run(cfg, ["demo-correct"], ["bare"], runs=1)


# ── in-image checks (the PR's ready gate): processes, grading user, real hooks ─

checker_support = load("checker_support")


def test_a_process_left_in_the_steps_group_is_killed_with_the_step(tmp_path: Path) -> None:
    probe = json.loads(
        (
            Path(runner.run(_cfg(tmp_path, "demo"), ["demo-correct"], ["bare"], runs=1)).parent
            / "demo-correct.bare.r0"
            / "s1"
            / "workspace"
            / "PROBE.json"
        ).read_text()
    )
    lingering = probe["lingering"]
    assert not runner._alive(lingering["in_group"])
    assert runner.check_lingering({"bare": probe}, separated=False) == []  # the detached one is killed, uncounted
    import time

    deadline = time.monotonic() + 20  # killed, it is a zombie until its new parent reaps it
    while runner._alive(lingering["detached"]) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not runner._alive(lingering["detached"])


def test_in_the_image_a_detached_survivor_is_a_failure() -> None:
    import subprocess as sp

    survivor = sp.Popen([sys.executable, "-c", "import time; time.sleep(60)"], start_new_session=True)
    try:
        failures = runner.check_lingering({"bare": {"lingering": {"detached": survivor.pid}}}, separated=True)
        assert failures == [f"bare: the probe's detached process {survivor.pid} survived the session"]
    finally:
        survivor.kill()
        survivor.wait()


def test_grading_reports_the_uid_its_candidate_runs_as(tmp_path: Path) -> None:
    import os

    result = runner._grading_probe(tmp_path)
    assert result == (False, f"uid {os.geteuid()}")  # outside the image: the caller
    assert runner.check_grading(result, separated=False) == []
    assert runner.check_grading((False, "uid 0"), separated=True)  # root is never acceptable in the image


def test_the_harness_never_kills_its_own_processes() -> None:
    import os

    with pytest.raises(ValueError, match="own processes"):
        checker_support.kill_user_processes(os.geteuid())


def test_a_failed_real_hook_or_a_missing_event_fails_the_demo() -> None:
    receipts = [
        {"chain_id": "c", "position": 0, "arm": "memkernel", "hooks": [{"event": "SessionStart", "exit_status": 1}]}
    ]
    failures = runner.check_real_hooks(receipts)
    assert "c s0: hook SessionStart exited 1" in failures and any("ran only" in f for f in failures)


# ── paid runs start only in the isolated image ─────────────────


def test_a_paid_run_outside_the_image_is_refused_before_anything_starts(tmp_path: Path) -> None:
    import os

    if os.geteuid() == 0:
        pytest.skip("the refusal of a non-root harness needs a non-root test")
    for phase in ("calibration", "measured"):
        cfg = _cfg(tmp_path / phase, phase)
        with pytest.raises(
            SystemExit, match=f"a {phase} run starts only in the isolated image: the harness is not root"
        ):
            runner.run(cfg, ["demo-correct"], ["bare"], runs=1)
        assert not (tmp_path / phase / "runs" / "t").exists()  # nothing created, nothing spent


def _image(monkeypatch: pytest.MonkeyPatch, readable: set[str], users: tuple[str, ...] = ("agent", "grader")) -> None:
    """Fake the image: root, the given users (agent 1001, grader 1002), and ``readable``: what agent's read gets."""
    import pwd
    import subprocess as sp

    ids = {"agent": 1001, "grader": 1002}

    def getpwnam(name: str) -> object:
        if name not in users:
            raise KeyError(name)
        return pwd.struct_passwd((name, "x", ids[name], ids[name], "", "/", "/usr/sbin/nologin"))

    def run(cmd: list[str], **kwargs: object) -> sp.CompletedProcess[bytes]:
        assert cmd[:5] == ["setpriv", "--reuid=1001", "--regid=1001", "--clear-groups", "--"]
        assert cmd[5] in ("ls", "cat") and cmd[6] == "--"  # a real listing or read, as the agent
        return sp.CompletedProcess(cmd, 0 if cmd[7] in readable else 1)

    monkeypatch.setattr(runner.os, "geteuid", lambda: 0)
    monkeypatch.setattr(pwd, "getpwnam", getpwnam)
    monkeypatch.setattr(runner.subprocess, "run", run)
    monkeypatch.setenv("LC_GRADER_UID", "1002")


def test_the_image_check_passes_only_with_both_users_and_a_repository_the_agent_cannot_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = _cfg(tmp_path, "calibration")
    cfg.agent_uid = 1001  # type: ignore[attr-defined]
    _image(monkeypatch, readable=set())
    runner.require_isolated_image(cfg)  # the image as built: passes
    _image(monkeypatch, readable={str(cfg.oracles_root)})  # type: ignore[attr-defined]
    with pytest.raises(SystemExit, match="the agent user can list .*demo-oracles"):
        runner.require_isolated_image(cfg)
    _image(monkeypatch, readable=set(), users=("agent",))
    with pytest.raises(SystemExit, match="there is no grader user"):
        runner.require_isolated_image(cfg)
    _image(monkeypatch, readable=set())
    cfg.agent_uid = None  # type: ignore[attr-defined]
    with pytest.raises(SystemExit, match="--agent-uid is None, not the agent user's 1001"):
        runner.require_isolated_image(cfg)


PROBES = json.loads((Path(__file__).resolve().parents[1] / "fixtures" / "lc-correct" / "probes.json").read_text())


@pytest.mark.parametrize("probe", PROBES["probes"], ids=lambda p: f"{p['chain']}:{p['answer'][:40]}")
def test_every_reviewer_probe_grades_as_pinned(probe: dict[str, str]) -> None:
    spec = correct_checker.load_spec(ORACLES_ROOT / f"lc-correct-{probe['chain']}")
    assert correct_checker.classify_text(probe["answer"], spec) == probe["expected"], probe["source"]


# ── leftover processes: setpriv … kill -KILL -- -1, then a check; chains start at 0 without gaps ─


def test_leftover_processes_are_killed_as_their_user_and_checked(monkeypatch: pytest.MonkeyPatch) -> None:
    import subprocess as sp

    calls: list[list[str]] = []
    alive = iter([[41, 42], [], []])  # before the kill, after it
    monkeypatch.setattr(checker_support, "user_processes", lambda uid: next(alive))
    monkeypatch.setattr("time.sleep", lambda s: None)
    monkeypatch.setattr(sp, "run", lambda cmd, **kw: calls.append(cmd) or sp.CompletedProcess(cmd, 0))
    assert checker_support.kill_user_processes(54321, 54320) == []
    # procps's kill needs "--" before -1, or it kills nothing (found in the image)
    assert calls == [["setpriv", "--reuid=54321", "--regid=54320", "--clear-groups", "--", "kill", "-KILL", "--", "-1"]]


def test_a_process_that_survives_the_kill_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    import subprocess as sp

    monkeypatch.setattr(checker_support, "user_processes", lambda uid: [99])
    monkeypatch.setattr(sp, "run", lambda cmd, **kw: sp.CompletedProcess(cmd, 0))
    assert checker_support.kill_user_processes(54321, rounds=2) == [99]


def test_an_agent_process_surviving_its_session_makes_the_session_invalid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = _cfg(tmp_path, "demo")
    cfg.agent_uid = cfg.agent_gid = 54321  # type: ignore[attr-defined]
    monkeypatch.setattr(runner.os, "geteuid", lambda: 0)  # as the image's root harness
    monkeypatch.setattr(runner, "_own", lambda *args, **kwargs: None)
    monkeypatch.setattr(runner, "kill_user_processes", lambda uid, gid: [4242])
    receipts_path = runner.run(cfg, ["demo-correct"], ["bare"], runs=1)
    (first,) = [json.loads(line) for line in receipts_path.read_text(encoding="utf-8").splitlines()]
    assert first["valid"] is False and first["invalid_reason"] == "agent_processes_survived"


def test_qualify_refuses_a_chain_that_skips_or_lacks_session_zero() -> None:
    gap = _complete({("a", "bare"): ["obsolete"], ("a", "informed"): ["informed"]})
    gap = [r for r in gap if not (r["chain_id"] == "a.bare.r0" and r["position"] == 0)]
    with pytest.raises(ValueError, match=r"a\.bare\.r0: sessions \[1\] do not run 0\.\.0 without a gap"):
        qualify.qualify(gap, ["a"], runs=1)


def test_the_report_refuses_a_chain_that_skips_or_lacks_session_zero() -> None:
    base = _receipt("bare", "lc-correct-a", "lc-correct", "obsolete", 1)
    with pytest.raises(ValueError, match=r"sessions \[1\] do not run 0\.\.n without a gap"):
        report.assemble([{**base, "position": 1}])
    with pytest.raises(ValueError, match=r"sessions \[0, 2\] do not run"):
        report.assemble([{**base, "position": 0, "stage": "exposure"}, {**base, "position": 2}])


def test_a_zombie_is_not_alive_with_or_without_proc() -> None:
    """The intermittent failure (2 of 10 fast-suite runs at d88b9d0): a killed process that its parent has not reaped
    yet is a zombie, and without /proc (macOS) it was read as alive."""
    import os
    import signal
    import subprocess as sp
    import time

    child = sp.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        assert runner._alive(child.pid)
        os.kill(child.pid, signal.SIGKILL)
        deadline = time.monotonic() + 10  # it becomes a zombie of ours, never reaped until wait()
        while (
            sp.run(["ps", "-o", "stat=", "-p", str(child.pid)], capture_output=True, text=True).stdout.strip()[:1]
            != "Z"
        ):
            assert time.monotonic() < deadline, "the killed child never showed as a zombie"
            time.sleep(0.05)
        assert not runner._alive(child.pid)
    finally:
        child.kill()
        child.wait()
    assert not runner._alive(child.pid)


# ── the agent removes part of its own session (the #166 review, finding 2) ─


def _deleting_agent(tmp_path: Path, what: str) -> tuple[str, ...]:
    """The stub agent, after which the session removes ``what``: its store, or its whole session folder."""
    script = tmp_path / f"agent_removes_{what}.py"
    script.write_text(
        "import os, runpy, shutil, sys\n"
        f"stub = {str(SUITE_DIR / 'stub_agent.py')!r}\n"
        "sys.argv = [stub, *sys.argv[1:]]\n"
        "try:\n"
        "    runpy.run_path(stub, run_name='__main__')\n"
        "finally:\n"
        f"    if {what!r} == 'store' and os.environ.get('MEMKERNEL_CHROMA_PERSIST_PATH'):\n"
        "        shutil.rmtree(os.environ['MEMKERNEL_CHROMA_PERSIST_PATH'], ignore_errors=True)\n"
        f"    if {what!r} == 'session':\n"
        "        shutil.rmtree(os.path.dirname(os.getcwd()), ignore_errors=True)\n",
        encoding="utf-8",
    )
    return (sys.executable, str(script))


@pytest.mark.parametrize(("what", "arm"), [("store", "memkernel"), ("session", "bare")])
def test_a_session_the_agent_partly_removed_is_invalid_with_its_receipt_written(
    tmp_path: Path, what: str, arm: str
) -> None:
    cfg = _cfg(tmp_path, "demo")
    cfg.agent_cmd = _deleting_agent(tmp_path, what)  # type: ignore[attr-defined]
    receipts_path = runner.run(cfg, ["demo-retain"], [arm], runs=1)
    receipts = [json.loads(line) for line in receipts_path.read_text(encoding="utf-8").splitlines()]
    assert receipts[0]["valid"] is False and receipts[0]["invalid_reason"] == "session_state_missing"
    assert list((receipts_path.parent / "sessions").iterdir()) == []  # nothing stranded under sessions/<token>
    assert (receipts_path.parent / f"demo-retain.{arm}.r0" / "s0" / "workspace").is_dir()

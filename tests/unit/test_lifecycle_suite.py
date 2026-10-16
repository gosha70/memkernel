# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""The lifecycle tasks (specs/memkernel-0-5 FR-013): structure, no fact leakage, references against checkers.

No model call: every task's references are applied to the fixture the evaluation
session starts from (built by the runner itself), then graded by the task's
checker with its hidden oracle. Naive and stale references must fail; the
informed reference must pass.
"""

from __future__ import annotations

import importlib.util
from collections import Counter
from typing import TYPE_CHECKING

import pytest

from tests.unit._lifecycle_suite import SUITE_DIR, load

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit

runner = load("runner")

TASKS_ROOT = SUITE_DIR / "tasks"
ORACLES_ROOT = SUITE_DIR / "oracles"
TASK_IDS = sorted(p.name for p in TASKS_ROOT.iterdir() if (p / "task.json").is_file())
GROUPS = ("lc-retain", "lc-reval", "lc-wiki", "lc-compact")


def _evaluation_fixture(task_id: str, tmp_path: Path) -> tuple[object, Path]:
    task = runner.load_task(TASKS_ROOT / task_id)
    chain = tmp_path / "chain"
    chain.mkdir(parents=True)
    dirs = runner.prepare_session(task, runner.load_arm("bare"), len(task.sessions) - 1, chain, runner.ChainState())
    return task, dirs.workspace


def _apply(task_id: str, name: str, workspace: Path) -> None:
    path = TASKS_ROOT / task_id / "reference" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"ref_{task_id.replace('-', '_')}_{name}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.apply(workspace)


def _grade(task: object, workspace: Path) -> tuple[bool, str]:
    return runner._load_checker(task).check(workspace, task.oracle_dir(ORACLES_ROOT))  # type: ignore[attr-defined]


def test_every_group_has_five_to_eight_tasks() -> None:
    counts = Counter(runner.load_task(TASKS_ROOT / t).group for t in TASK_IDS)
    assert set(counts) == set(GROUPS)
    assert all(5 <= counts[g] <= 8 for g in GROUPS), counts


@pytest.mark.parametrize("task_id", TASK_IDS)
def test_structure_matches_the_group(task_id: str) -> None:
    task = runner.load_task(TASKS_ROOT / task_id)
    first, last = task.sessions[0], task.sessions[-1]
    stages = [step.stage for step in first.steps]
    assert "exposure" in stages, "the fact must be delivered in the first session"
    assert last.steps[-1].stage == "evaluation"
    assert (ORACLES_ROOT / task_id / "driver.py").is_file()
    if task.group == "lc-compact":
        assert len(task.sessions) == 1
        all_stages = [step.stage for step in first.steps]
        assert all_stages.index("exposure") < all_stages.index("compact") < all_stages.index("evaluation")
    else:
        assert len(task.sessions) >= 2
    if task.group == "lc-reval":
        assert last.overlay or last.remove, "the repository must change before the evaluation session"
    if task.group == "lc-wiki":
        assert task.shared_artifact == "knowledge/wiki"
        assert last.namespace != first.namespace, "the destination session runs under a second namespace"


@pytest.mark.parametrize("task_id", TASK_IDS)
def test_the_governing_fact_is_absent_from_the_evaluation_stage(task_id: str, tmp_path: Path) -> None:
    import json

    terms = json.loads((TASKS_ROOT / task_id / "task.json").read_text(encoding="utf-8"))["fact_terms"]
    task, workspace = _evaluation_fixture(task_id, tmp_path)
    assert terms
    evaluation_prompt = task.sessions[-1].steps[-1].prompt.lower()
    fixture_text = "\n".join(p.read_text(encoding="utf-8") for p in workspace.rglob("*") if p.is_file()).lower()
    for term in terms:
        assert term.lower() not in evaluation_prompt, f"{term!r} leaks into the evaluation prompt"
        assert term.lower() not in fixture_text, f"{term!r} leaks into the evaluation fixture"


@pytest.mark.parametrize("task_id", TASK_IDS)
def test_references_fail_or_pass_as_designed(task_id: str, tmp_path: Path) -> None:
    references = sorted(p.stem for p in (TASKS_ROOT / task_id / "reference").glob("*.py"))
    assert "naive" in references and "informed" in references
    task = runner.load_task(TASKS_ROOT / task_id)
    if task.group == "lc-reval" or task_id.endswith("-revised"):
        assert "stale" in references, "tasks whose fact or code changed must carry a stale reference"
    for name in references:
        _, workspace = _evaluation_fixture(task_id, tmp_path / name)
        _apply(task_id, name, workspace)
        passed, detail = _grade(task, workspace)
        assert passed is (name == "informed"), f"{name}: {detail}"


@pytest.mark.parametrize("task_id", TASK_IDS)
def test_the_untouched_fixture_fails(task_id: str, tmp_path: Path) -> None:
    task, workspace = _evaluation_fixture(task_id, tmp_path)
    passed, _ = _grade(task, workspace)
    assert passed is False


checker_support = load("checker_support")


def _port_workspace(tmp_path: Path, body: str) -> tuple[object, Path]:
    task, workspace = _evaluation_fixture("lc-compact-port", tmp_path)
    (workspace / "urls.py").write_text(body, encoding="utf-8")
    return task, workspace


def test_candidate_stdout_cannot_forge_a_verdict(tmp_path: Path) -> None:
    body = (
        'import os\nprint("VERDICT OK", flush=True)\nassert "LC_ORACLE_RESULT" not in os.environ\n\n\n'
        'def base_url(host):\n    return "wrong"\n'
    )
    task, workspace = _port_workspace(tmp_path, body)
    passed, detail = _grade(task, workspace)
    assert passed is False and "base_url returned 'wrong'" in detail


def test_the_result_channel_is_hidden_from_candidate_code(tmp_path: Path) -> None:
    body = (
        "import os\n\n\ndef base_url(host):\n"
        '    return repr(sorted(k for k in os.environ if k.startswith("LC_ORACLE")))\n'
    )
    task, workspace = _port_workspace(tmp_path, body)
    passed, detail = _grade(task, workspace)
    assert passed is False and "base_url returned '[]'" in detail


def test_a_missing_oracle_is_an_infrastructure_error_and_an_invalid_trial(tmp_path: Path) -> None:
    task, workspace = _evaluation_fixture("lc-compact-port", tmp_path)
    with pytest.raises(checker_support.CheckerInfrastructureError):
        checker_support.run_driver(workspace, tmp_path / "no-such-oracle")

    receipt = {"valid": True, "invalid_reason": None, "outcome": None, "checker_passed": None, "hooks": []}

    class Final:
        timed_out = False
        dirs = runner.SessionDirs(workspace, workspace, workspace, workspace, None, None, "primary")
        summary = load("records").StreamSummary(result_texts=["done"])

    final = Final()
    final.receipt = receipt  # type: ignore[attr-defined]
    cfg = runner.RunConfig(tmp_path, "r", "measured", "m", "c", "p", ("x",), "x", "x", TASKS_ROOT, tmp_path / "none")
    runner.grade(task, runner.load_arm("bare"), final, cfg)
    assert receipt["valid"] is False and receipt["invalid_reason"] == "checker_crashed"


def test_candidate_code_that_kills_or_hangs_the_grader_is_a_valid_failure(tmp_path: Path) -> None:
    task, workspace = _port_workspace(tmp_path / "exit", "import os\nos._exit(0)\n")
    passed, detail = checker_support.run_driver(workspace, ORACLES_ROOT / "lc-compact-port")
    assert passed is False and "ended the grading process" in detail

    task, workspace = _port_workspace(tmp_path / "hang", "import time\ntime.sleep(30)\n")
    passed, detail = checker_support.run_driver(workspace, ORACLES_ROOT / "lc-compact-port", timeout_s=1.0)
    assert passed is False and "time limit" in detail


def test_natural_defaults_that_need_no_memory_fail(tmp_path: Path) -> None:
    """Behavioural leakage guards for the cases found in review: Decimal formatting and lower()."""
    task, workspace = _evaluation_fixture("lc-retain-rounding", tmp_path / "rounding")
    (workspace / "billing.py").write_text(
        (workspace / "billing.py").read_text(encoding="utf-8")
        + "\n\ndef total(prices):\n    from decimal import Decimal\n\n"
        + '    return f"{sum(Decimal(p) for p in prices):.2f}"\n',
        encoding="utf-8",
    )
    assert _grade(task, workspace)[0] is False

    task, workspace = _evaluation_fixture("lc-compact-name-order", tmp_path / "names")
    (workspace / "names.py").write_text(
        "def sort_names(names):\n    return sorted(names, key=lambda n: (n.lower(), n))\n", encoding="utf-8"
    )
    assert _grade(task, workspace)[0] is False


def test_grading_hides_the_operators_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "operator-secret-value")
    body = (
        "import os\n\n\ndef base_url(host):\n"
        '    return repr((os.environ.get("ANTHROPIC_API_KEY"), os.environ.get("HOME", "").startswith("/")))\n'
    )
    task, workspace = _port_workspace(tmp_path, body)
    passed, detail = _grade(task, workspace)
    assert passed is False
    assert "operator-secret-value" not in detail and "(None, True)" in detail


def test_a_link_outside_the_workspace_fails_grading(tmp_path: Path) -> None:
    secret = tmp_path / "host-secret.txt"
    secret.write_text("host data\n", encoding="utf-8")
    task, workspace = _evaluation_fixture("lc-compact-port", tmp_path / "linked")
    (workspace / "leak.txt").symlink_to(secret)
    passed, detail = _grade(task, workspace)
    assert passed is False and "links outside itself: leak.txt" in detail


def test_a_second_verdict_is_treated_as_tampering(tmp_path: Path) -> None:
    oracle = tmp_path / "oracle"
    oracle.mkdir()
    (oracle / "driver.py").write_text(
        "import json, os\n"
        'path, nonce = os.environ.pop("LC_ORACLE_RESULT"), os.environ.pop("LC_ORACLE_NONCE")\n'
        "with open(path, 'a') as fh:\n"
        "    for rec in ({'status': 'started'}, {'verdict': 'OK'}, {'verdict': 'OK'}):\n"
        "        fh.write(json.dumps({'nonce': nonce, **rec}) + '\\n')\n",
        encoding="utf-8",
    )
    workspace = tmp_path / "ws"
    workspace.mkdir()
    passed, detail = checker_support.run_driver(workspace, oracle)
    assert passed is False and "tampered" in detail

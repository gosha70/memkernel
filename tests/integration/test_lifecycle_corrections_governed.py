# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""lc-correct's correction events against a real store and the real wiki-studio (memkernel-0-16 FR-002, FR-004).

Session 0 is played in-process (a retain, and for the governed arms an export through the gate) in the chain's own
environment; the correction then runs exactly as the runner runs it, through ``memkernel_ops.py`` (with the test
suite's MockEmbedding, tests/unit/_lc_ops_shim.py) and the wiki-studio command line.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import pytest

from memkernel.core.models import MemoryType
from memkernel.factory import build_service
from memkernel.wiki.sync import WikiExporter
from tests.conftest import MockEmbedding
from tests.unit._lifecycle_suite import SUITE_DIR, load
from tests.unit.test_wiki import NO_EXTRA_ENV

pytestmark = pytest.mark.integration

try:  # fails, never skips, without wiki-studio, unless MK_TEST_NO_EXTRA=1 marks a deliberate no-extra run
    import wiki_studio  # noqa: F401
except ImportError:
    if os.environ.get(NO_EXTRA_ENV) == "1":
        pytest.skip("deliberate no-extra run", allow_module_level=True)
    raise

runner = load("runner")
corrections = load("corrections")
SHIM = Path(__file__).resolve().parents[1] / "unit" / "_lc_ops_shim.py"
WIKI_STUDIO = str(Path(sys.executable).with_name("wiki-studio"))
DEPLOY = "lc-correct-deploy-window"  # replacement
TOKEN = "lc-correct-token-lifetime"  # withdrawal
X_DEPLOY = "Deploy window\n\nDeploys may go out on Fridays after 17:00 UTC."


class Chain:
    """One lc-correct chain for one arm: session 0's directories, then session 1's after the exposure copy."""

    def __init__(self, tmp_path: Path, task_id: str, arm_name: str, monkeypatch: pytest.MonkeyPatch) -> None:
        self.task = runner.load_task(SUITE_DIR / "tasks" / task_id)
        self.arm = runner.load_arm(arm_name)
        self.chain = tmp_path / f"{task_id}.{arm_name}.r0"
        self.chain.mkdir()
        self.cfg = runner.RunConfig(
            run_root=tmp_path,
            run_id="t",
            phase="demo",
            model="stub",
            code_sha="t",
            preregistration_sha256=None,
            agent_cmd=("unused",),
            memkernel_cmd="unused",
            memkernel_python=sys.executable,
            tasks_root=SUITE_DIR / "tasks",
            oracles_root=SUITE_DIR / "oracles",
            ops_command=(sys.executable, str(SHIM)),
            wiki_studio_cmd=WIKI_STUDIO,
        )
        self.s0 = runner.prepare_session(self.task, self.arm, 0, self.chain, runner.ChainState())
        for key, value in runner._memkernel_env(self.s0, self.chain.name, self.cfg, self.arm.wiki_governed).items():
            monkeypatch.setenv(key, value)
        self.s1: Any = None

    def service(self) -> Any:
        return build_service(embedding=MockEmbedding())

    def export(self, svc: Any) -> list[str]:
        ws = self.s0.workspace
        report = WikiExporter(
            svc, ws / "knowledge" / "wiki", project_root=ws, proposals_dir=ws / runner.GOVERNED_PROPOSALS_DIR
        ).export()
        assert report.gated, report.gate_error
        return list(report.written)

    def deliver(self) -> dict[str, Any]:
        self.s1 = runner.prepare_session(
            self.task, self.arm, 1, self.chain, runner.ChainState(workspace=self.s0.workspace)
        )
        ops = runner._ops(self.arm, self.s1, self.chain.name, self.cfg)
        cli = runner._cli(self.arm, self.s1, self.chain.name, self.cfg) if self.arm.wiki_governed else None
        result: dict[str, Any] = corrections.deliver(
            self.arm.name, self.task.correction, self.s1.workspace, self.s1.memory_dir, ops, cli
        )
        return result

    def gate(self) -> dict[str, Any]:
        outcome = runner.SessionOutcome({}, None, self.s1, [], False)
        runner.check_gate(self.task, self.arm, outcome, self.chain.name, self.cfg)
        gate: dict[str, Any] = outcome.receipt["gate"]
        return gate

    def cli(self, *args: str) -> tuple[int, str]:
        result: tuple[int, str] = runner._cli(self.arm, self.s1, self.chain.name, self.cfg)(*args)
        return result


def test_the_scripted_curator_corrects_the_exported_draft_through_the_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    chain = Chain(tmp_path, DEPLOY, "memkernel_governed", monkeypatch)
    svc = chain.service()
    x_ref = svc.retain(X_DEPLOY, MemoryType.DECISION)
    (draft,) = chain.export(svc)
    result = chain.deliver()
    assert result["delivered"] and result["refusals"] == []
    landed = result["landed"]
    assert landed == [draft.removeprefix("knowledge/wiki/")] or landed == [draft]
    assert result["imported"]["corrections"] == [{"page": landed[0], "ref_id": x_ref}]
    after = chain.service()
    assert after.get(x_ref, touch=False).superseded_by is not None
    page = (chain.s1.workspace / "knowledge" / "wiki" / landed[0]).read_text(encoding="utf-8")
    assert "status: stable" in page and f"corrects: {x_ref}" in page and "Monday at 09:00 UTC" in page
    gate = chain.gate()
    assert gate["breaches"] == [] and gate["approved"] == landed and gate["unreviewed_drafts"] == []
    assert gate["lint_violations"] == 0


def test_the_scripted_curator_refuses_when_no_draft_carries_the_obsolete_rule(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    chain = Chain(tmp_path, DEPLOY, "memkernel_governed", monkeypatch)
    x_ref = chain.service().retain(X_DEPLOY, MemoryType.DECISION)  # retained, never exported
    result = chain.deliver()
    assert result["delivered"] is False and result["landed"] == []
    assert result["refusals"] == [{"page": "", "reason": "no exported draft carries the obsolete rule"}]
    assert chain.service().get(x_ref, touch=False).superseded_by is None
    assert chain.gate()["breaches"] == []


def test_the_oracle_lands_the_rule_and_corrects_every_memory_carrying_the_obsolete_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    chain = Chain(tmp_path, DEPLOY, "memkernel_governed_oracle", monkeypatch)
    x_ref = chain.service().retain(X_DEPLOY, MemoryType.DECISION)
    result = chain.deliver()
    assert result["delivered"] and len(result["landed"]) == 1
    assert result["imported"]["corrections"] == [{"page": result["landed"][0], "ref_id": x_ref}]
    assert chain.service().get(x_ref, touch=False).superseded_by is not None
    gate = chain.gate()
    assert gate["breaches"] == [] and gate["approved"] == result["landed"]


@pytest.mark.parametrize(("task_id", "x_text"), [(DEPLOY, X_DEPLOY), (TOKEN, "Refresh tokens are valid for 24 hours.")])
def test_the_memkernel_arm_supersedes_or_withdraws_per_the_chain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, task_id: str, x_text: str
) -> None:
    chain = Chain(tmp_path, task_id, "memkernel", monkeypatch)
    x_ref = chain.service().retain(x_text, MemoryType.DECISION)
    result = chain.deliver()
    assert result["matched"] == [x_ref]
    after = chain.service()
    old, new = after.get(x_ref, touch=False), after.get(result["new_ref"], touch=False)
    assert new is not None and chain.task.correction["headline"] in new.content
    if chain.task.correction["kind"] == "replacement":
        assert old.superseded_by == result["new_ref"] and new.supersedes == x_ref
    else:
        assert old.withdrawn_reason == "deprecated" and old.superseded_by is None and new.supersedes is None


def test_the_gate_check_counts_a_direct_write_and_an_unapproved_promotion_as_breaches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    chain = Chain(tmp_path, DEPLOY, "memkernel_governed", monkeypatch)
    svc = chain.service()
    svc.retain(X_DEPLOY, MemoryType.DECISION)
    svc.retain("Feature freeze\n\nNo merges to main during the feature freeze.", MemoryType.DECISION)
    chain.export(svc)  # two drafts: one corrected and approved, one left as an unreviewed draft
    chain.deliver()
    wiki = chain.s1.workspace / "knowledge" / "wiki"
    staged = tmp_path / "staged"
    (staged / "concepts").mkdir(parents=True)
    page = (wiki / "concepts" / "release-environments.md").read_text(encoding="utf-8")
    (staged / "concepts" / "staging.md").write_text(
        page.replace("slug: release-environments", "slug: staging"), encoding="utf-8"
    )
    (staged / "index.md").write_text("- [Staging](concepts/staging.md) — staging.\n", encoding="utf-8")
    code, out = chain.cli("propose", "--from", str(staged), "--promote", "--by", "agent")  # promoted, not approved
    assert code == 0, out
    direct = wiki / "decisions" / "direct.md"  # written past the gate, last: it would fail the promote's lint
    direct.write_text((wiki / "workflows" / "release-checklist.md").read_text(encoding="utf-8"), encoding="utf-8")
    gate = chain.gate()
    reasons = {b["page"]: b["reason"] for b in gate["breaches"]}
    assert reasons == {"decisions/direct.md": "no_receipt", "concepts/staging.md": "no_approval"}
    assert len(gate["unreviewed_drafts"]) == 1 and len(gate["approved"]) == 1
    assert gate["lint_violations"] > 0  # the direct write also breaks the wiki's structure

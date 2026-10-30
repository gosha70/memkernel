# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""The wiki-bridge wiring check (eval/lifecycle-suite/wiring/wiring_check.py, task 18a).

Fast tests (run in CI) check the transfer judgement, ``transfer_findings``, on the
checked-in fixture through the runner's own ``prepare_session``: a clean transfer
passes, a leaked file or a changed fixture file fails. The two slow tests start
the real memkernel MCP server over stdio (which loads the embedding model) and
run the whole check, once clean and once with a leaking transfer.
"""

from __future__ import annotations

import importlib.util
import shutil
import sys
from pathlib import Path
from typing import Any

import pytest

from tests.unit._lifecycle_suite import SUITE_DIR

pytestmark = [pytest.mark.unit]

CHECK = SUITE_DIR / "wiring" / "wiring_check.py"


def _check_module() -> Any:
    spec = importlib.util.spec_from_file_location("wiring_check", CHECK)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _memkernel() -> str:
    found = shutil.which("memkernel", path=str(Path(sys.executable).parent))
    if found is None:
        pytest.skip("the memkernel console script is not installed next to this interpreter")
    return found


def _steps(report: dict[str, Any]) -> dict[str, bool]:
    return {step["step"]: step["passed"] for step in report["steps"]}


@pytest.mark.slow
def test_the_wiki_bridge_carries_a_fact_into_an_empty_second_namespace_on_both_paths() -> None:
    """#81 (memkernel-0-7-wiring-spool SC-1): governed (curated and approved) and ungoverned (wiki-studio hidden)."""
    report = _check_module().run_check(SUITE_DIR, _memkernel(), sys.executable, None, "both")
    assert report["passed"], report
    assert report["legs"] == ["governed", "ungoverned"]
    steps = _steps(report)
    for leg in ("governed", "ungoverned"):
        assert steps[f"{leg}: destination store starts with 0 records"]
        assert steps[f"{leg}: recall finds nothing before import"]
        assert steps[f"{leg}: get returns the synthetic sentence verbatim"]
        assert steps[f"{leg}: wiki_import was {leg}"]
    assert steps["governed: the exported page was marked stable and approved"]


def test_the_stub_makes_memkernel_see_no_wiki_studio(tmp_path: Path) -> None:
    """SC-3: with the stub first on PYTHONPATH, memkernel's load_studio() treats wiki-studio as absent."""
    import os
    import subprocess

    stub = _check_module().write_stub(tmp_path / "hide")
    probe = "from memkernel.wiki.studio import load_studio; print(load_studio() is None)"
    env = {**os.environ, "PYTHONPATH": str(stub)}
    hidden = subprocess.run([sys.executable, "-c", probe], env=env, capture_output=True, text=True, check=True)
    visible = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, check=True)

    assert hidden.stdout.strip() == "True"
    assert visible.stdout.strip() == ("False" if _check_module().studio_version(sys.executable) else "True")


def test_auto_follows_the_wiki_studio_version(monkeypatch: pytest.MonkeyPatch) -> None:
    """SC-2: auto is governed with wiki-studio >= 0.7.0, else ungoverned; both runs governed then ungoverned."""
    check = _check_module()
    for version, legs in (
        ("0.7.0", ["governed"]),
        ("0.8.1", ["governed"]),
        ("0.6.0", ["ungoverned"]),
        ("", ["ungoverned"]),
    ):
        monkeypatch.setattr(check, "studio_version", lambda python, v=version: v)
        assert check.resolve_wiki_path("auto", sys.executable) == legs
    assert check.resolve_wiki_path("both", sys.executable) == ["governed", "ungoverned"]
    assert check.resolve_wiki_path("ungoverned", sys.executable) == ["ungoverned"]


def test_governed_without_wiki_studio_fails_with_a_named_step(monkeypatch: pytest.MonkeyPatch) -> None:
    """SC-2: the governed leg stops at its first step, before any server is started."""
    check = _check_module()
    monkeypatch.setattr(check, "studio_version", lambda python: "")

    report = check.run_check(SUITE_DIR, "memkernel-not-started", sys.executable, None, "governed")

    assert report["passed"] is False
    assert report["steps"] == [
        {"step": "the server's interpreter has wiki-studio (governed leg)", "passed": False, "version": ""}
    ]


@pytest.mark.slow
def test_a_transfer_that_leaks_more_than_the_wiki_fails_the_check(monkeypatch: pytest.MonkeyPatch) -> None:
    check = _check_module()
    sys.path.insert(0, str(SUITE_DIR))
    import runner  # type: ignore[import-not-found]

    real = runner.prepare_session

    def leaky(task: Any, arm: Any, position: int, chain: Path, state: Any) -> Any:
        dirs = real(task, arm, position, chain, state)
        if position == 1 and state.workspace is not None:
            shutil.copy(state.workspace / check.NOTES, dirs.workspace / check.NOTES)
        return dirs

    monkeypatch.setattr(runner, "prepare_session", leaky)
    report = check.run_check(SUITE_DIR, _memkernel(), sys.executable, None)
    assert report["passed"] is False
    assert _steps(report)["only knowledge/wiki/ crossed over"] is False


def _transfer(
    tmp_path: Path, *, leak: bool = False, edit_readme: bool = False, drop_readme: bool = False, export: bool = True
) -> dict[str, Any]:
    """Source session on the fixture, a page written as wiki_export would, then the runner's transfer."""
    check = _check_module()
    sys.path.insert(0, str(SUITE_DIR))
    import runner  # type: ignore[import-not-found]

    task, arm = runner.load_task(check.FIXTURE_DIR), runner.load_arm("memkernel")
    chain = tmp_path / "chain"
    chain.mkdir()
    source = runner.prepare_session(task, arm, 0, chain, runner.ChainState())
    if export:
        page = source.workspace / runner.WIKI_DIR / "decisions" / "wiring-fact.md"
        page.parent.mkdir(parents=True)
        page.write_text("---\npage_type: decision\n---\n\n# Wiring fact\n", encoding="utf-8")
    (source.workspace / check.NOTES).write_text("must not cross\n", encoding="utf-8")
    destination = runner.prepare_session(
        task, arm, 1, chain, runner.ChainState(workspace=source.workspace, transcripts=[])
    )
    if leak:
        shutil.copy(source.workspace / check.NOTES, destination.workspace / check.NOTES)
    if edit_readme:
        (destination.workspace / "README.md").write_text("changed\n", encoding="utf-8")
    if drop_readme:
        (destination.workspace / "README.md").unlink()
    return check.transfer_findings(task.tree, destination.workspace, runner.WIKI_DIR)


def test_a_clean_transfer_carries_only_the_wiki(tmp_path: Path) -> None:
    findings = _transfer(tmp_path)
    assert findings["only_wiki_crossed"] and not findings["changed_outside_wiki"] and not findings["missing"]
    assert findings["crossed"] == ["knowledge/wiki/decisions/wiring-fact.md"]


def test_a_leaked_file_fails_the_transfer_judgement(tmp_path: Path) -> None:
    findings = _transfer(tmp_path, leak=True)
    assert findings["only_wiki_crossed"] is False and "NOTES.md" in findings["crossed"]


def test_a_changed_fixture_file_outside_the_wiki_is_reported(tmp_path: Path) -> None:
    findings = _transfer(tmp_path, edit_readme=True)
    assert findings["changed_outside_wiki"] == ["README.md"]


def test_a_fixture_file_missing_from_the_destination_is_reported_not_raised(tmp_path: Path) -> None:
    findings = _transfer(tmp_path, drop_readme=True)
    assert findings["missing"] == ["README.md"] and findings["changed_outside_wiki"] == []


def test_a_transfer_that_carries_nothing_fails(tmp_path: Path) -> None:
    findings = _transfer(tmp_path, export=False)
    assert findings["only_wiki_crossed"] is False and findings["crossed"] == []

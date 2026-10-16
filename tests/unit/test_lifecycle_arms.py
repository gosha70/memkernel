# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""Frozen per-arm persistence rules (specs/memkernel-0-5 FR-012, SC-8)."""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

import pytest

from tests.unit._lifecycle_suite import REPO_ROOT, SUITE_DIR, load

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit

runner = load("runner")

EXPECTED = {  # arm: (workspace, transcripts, store)
    "bare": (False, False, False),
    "placebo": (False, False, False),
    "protocol": (False, False, False),
    "claude_md": (True, False, False),
    "fs_grep": (False, True, False),
    "memkernel": (False, False, True),
}


def _task(tmp_path: Path, *, shared: bool = False, namespace: str = "primary") -> object:
    root = tmp_path / "task"
    (root / "tree").mkdir(parents=True)
    (root / "tree" / "README.md").write_text("fixture\n", encoding="utf-8")
    spec = {
        "task_id": "t1",
        "group": "lc-wiki" if shared else "lc-retain",
        "sessions": [
            {"steps": [{"stage": "exposure", "prompt": "learn"}]},
            {"namespace": namespace, "steps": [{"stage": "evaluation", "prompt": "use"}]},
        ],
    }
    if shared:
        spec["shared_artifact"] = "knowledge/wiki"
    (root / "task.json").write_text(json.dumps(spec), encoding="utf-8")
    return runner.load_task(root)


def _previous_session(tmp_path: Path) -> object:
    workspace = tmp_path / "previous" / "workspace"
    (workspace / "knowledge" / "wiki").mkdir(parents=True)
    (workspace / "README.md").write_text("fixture\n", encoding="utf-8")
    (workspace / "NOTES.md").write_text("what the agent wrote\n", encoding="utf-8")
    (workspace / "knowledge" / "wiki" / "page.md").write_text("exported\n", encoding="utf-8")
    transcript = tmp_path / "previous" / "transcript-0.md"
    transcript.write_text("# Earlier session\n", encoding="utf-8")
    return runner.ChainState(workspace=workspace, transcripts=[transcript])


@pytest.mark.parametrize("arm_name", sorted(EXPECTED))
def test_each_arm_carries_exactly_what_its_rule_permits(tmp_path: Path, arm_name: str) -> None:
    arm = runner.load_arm(arm_name)
    assert (arm.persist_workspace, arm.persist_transcripts, arm.persist_store) == EXPECTED[arm_name]
    chain = tmp_path / "chain"
    chain.mkdir()
    store_marker = chain / "store" / "primary" / "marker"
    store_marker.parent.mkdir(parents=True)
    store_marker.write_text("from session 0\n", encoding="utf-8")

    dirs = runner.prepare_session(_task(tmp_path), arm, 1, chain, _previous_session(tmp_path))

    workspace_files = {p.relative_to(dirs.workspace).as_posix() for p in dirs.workspace.rglob("*") if p.is_file()}
    expected_files = {"README.md"} | ({"NOTES.md", "knowledge/wiki/page.md"} if arm.persist_workspace else set())
    assert workspace_files == expected_files
    assert (dirs.memory_dir is not None and (dirs.memory_dir / "session-0.md").is_file()) == arm.persist_transcripts
    assert (dirs.store is not None and (dirs.store / "marker").is_file()) == arm.persist_store
    assert not any(dirs.home.iterdir()) and not any(dirs.config.iterdir())  # fresh HOME and config every session


@pytest.mark.parametrize("arm_name", sorted(EXPECTED))
def test_lc_wiki_shared_artifact_reaches_every_arm_and_the_destination_store_is_empty(
    tmp_path: Path, arm_name: str
) -> None:
    arm = runner.load_arm(arm_name)
    chain = tmp_path / "chain"
    (chain / "store" / "primary").mkdir(parents=True)
    (chain / "store" / "primary" / "marker").write_text("source namespace\n", encoding="utf-8")

    dirs = runner.prepare_session(
        _task(tmp_path, shared=True, namespace="second"), arm, 1, chain, _previous_session(tmp_path)
    )

    assert (dirs.workspace / "knowledge" / "wiki" / "page.md").read_text(encoding="utf-8") == "exported\n"
    assert (dirs.workspace / "NOTES.md").exists() == arm.persist_workspace  # nothing else crosses over
    if arm.persist_store:
        assert dirs.store is not None and dirs.store.name == "second" and not any(dirs.store.iterdir())


def test_memkernel_and_protocol_carry_the_template_block_byte_for_byte() -> None:
    template = (REPO_ROOT / "templates" / "claude-memory-instructions.md").read_text(encoding="utf-8")
    match = re.search(r"## Minimal setup \(paste into CLAUDE.md\)\n\n```markdown\n(.*?)\n```\n", template, re.S)
    assert match is not None
    block = match.group(1) + "\n"
    assert runner.load_arm("memkernel").instruction.decode() == block
    assert runner.load_arm("protocol").instruction.decode() == block


def test_placebo_is_length_matched_within_five_percent() -> None:
    memkernel = len(runner.load_arm("memkernel").instruction)
    placebo = len(runner.load_arm("placebo").instruction)
    assert abs(placebo - memkernel) / memkernel <= 0.05


def test_only_memkernel_has_memory_tools_server_and_hooks() -> None:
    for name in EXPECTED:
        arm = runner.load_arm(name)
        has_memory = any(tool.startswith("mcp__memkernel__") for tool in arm.allowed_tools)
        assert has_memory == arm.mcp == bool(arm.hooks) == (name == "memkernel")
    assert set(runner.load_arm("memkernel").hooks) == {"SessionStart", "PreCompact", "PostCompact"}


def test_arm_config_hash_covers_the_instruction(tmp_path: Path) -> None:
    import shutil

    arms = tmp_path / "arms"
    shutil.copytree(SUITE_DIR / "arms", arms)
    before = runner.load_arm("placebo", arms).config_sha256
    (arms / "placebo" / "instruction.md").write_text("changed\n", encoding="utf-8")
    assert runner.load_arm("placebo", arms).config_sha256 != before

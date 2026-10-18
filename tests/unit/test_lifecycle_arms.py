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
    "wiki_studio": (False, False, False),
}
WIKI_STUDIO_INSTRUCTION_SHA256 = "c231bb4077e058da89470455b7f318aafc6966e8f07ead74ab2413a835c6355b"  # v0.4.0 blob


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


def test_wiki_studio_arm_is_wiki_studio_v040_byte_for_byte_plus_three_keys() -> None:
    """The instruction and the upstream keys are exactly docs/agent-arm/ at wiki-studio v0.4.0 (e9ec3fa)."""
    import hashlib

    config = json.loads((SUITE_DIR / "arms" / "wiki_studio" / "config.frozen.json").read_text(encoding="utf-8"))
    source = config["source"]
    assert source["tag"] == "v0.4.0" and source["commit"].startswith("e9ec3fa")
    assert source["added_here"] == ["groups", "cli_pin", "source"]
    instruction = runner.load_arm("wiki_studio").instruction
    assert hashlib.sha256(instruction).hexdigest() == source["instruction_sha256"] == WIKI_STUDIO_INSTRUCTION_SHA256
    upstream = {key: value for key, value in config.items() if key not in source["added_here"]}
    assert hashlib.sha256((json.dumps(upstream, indent=2) + "\n").encode()).hexdigest() == source["config_sha256"]


def test_wiki_studio_runs_on_lc_wiki_only_with_its_cli_pinned() -> None:
    arm = runner.load_arm("wiki_studio")
    assert arm.groups == ("lc-wiki",) and arm.cli_pin == ("wiki-studio", "0.4.0")
    assert arm.allowed_tools == runner.BASE_TOOLS and not arm.mcp and not arm.hooks
    groups = {runner.load_task(path).group: runner.load_task(path) for path in (SUITE_DIR / "tasks").iterdir()}
    assert {group for group, task in groups.items() if arm.runs_on(task)} == {"lc-wiki"}
    assert all(
        runner.load_arm(name).runs_on(task) for name in EXPECTED if name != "wiki_studio" for task in groups.values()
    )


def test_wiki_studio_instruction_is_length_matched_within_five_percent() -> None:
    memkernel = len(runner.load_arm("memkernel").instruction)
    wiki_studio = len(runner.load_arm("wiki_studio").instruction)
    assert abs(wiki_studio - memkernel) / memkernel <= 0.05


def test_wiki_studio_instruction_never_runs_a_nested_model() -> None:
    text = runner.load_arm("wiki_studio").instruction.decode()
    assert "wiki-studio find" in text and 'wiki-studio propose --from "$D" --promote' in text
    assert "Run wiki-studio ingest or wiki-studio query: they start another model." in text  # listed under Never

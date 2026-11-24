# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""The Codex, Cursor and Antigravity templates parse as their tools' documented formats (#107 FR-004, SC-4)."""

from __future__ import annotations

import json
import shlex
import tomllib
from pathlib import Path

import pytest

from memkernel.lifecycle import HEADING_POST_COMPACT, HEADING_SESSION_START

pytestmark = pytest.mark.unit

TEMPLATES = Path(__file__).resolve().parents[2] / "templates"
RECOVERED = "Recovered from MemKernel"
SESSION_START = "memkernel session-start"
FIRST_RECALL = 'recall(query="session checkpoint", checkpoint_only=true, order="newest", top_k=1)'


def _frontmatter(path: Path) -> dict[str, str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "---"
    end = lines.index("---", 1)
    pairs = (line.split(":", 1) for line in lines[1:end])
    return {key.strip(): value.strip().strip('"') for key, value in pairs}


def test_codex_config_registers_memkernel_over_stdio_and_http() -> None:
    stdio = tomllib.loads((TEMPLATES / "codex" / "config.toml").read_text(encoding="utf-8"))
    assert stdio["mcp_servers"]["memkernel"]["command"] == "memkernel"
    assert "MEMKERNEL_CHROMA_PERSIST_PATH" in stdio["mcp_servers"]["memkernel"]["env"]
    http = tomllib.loads((TEMPLATES / "codex" / "config.http.toml").read_text(encoding="utf-8"))
    assert http["mcp_servers"]["memkernel"]["url"] == "http://127.0.0.1:8765/mcp"


def _codex_hook() -> dict[str, str]:
    hooks = json.loads((TEMPLATES / "codex" / "hooks.json").read_text(encoding="utf-8"))
    (entry,) = hooks["hooks"]["SessionStart"]
    assert set(entry["matcher"].split("|")) == {"startup", "clear", "compact"}
    (hook,) = entry["hooks"]
    assert hook["type"] == "command"
    command: dict[str, str] = hook
    return command


def test_codex_hook_runs_session_start_with_the_6000_character_cap() -> None:
    """D3: a hook for Codex only; D5: --max-chars 6000."""
    assert _codex_hook()["command"].endswith(f" {SESSION_START} --format plain --max-chars 6000")


def test_codex_hook_opens_the_store_the_mcp_server_opens() -> None:
    """[mcp_servers.memkernel.env] reaches only the MCP server; the hook is its own process, so its command sets the
    same MEMKERNEL_* values, or it opens the default store and finds no checkpoint."""
    server_env = tomllib.loads((TEMPLATES / "codex" / "config.toml").read_text(encoding="utf-8"))["mcp_servers"][
        "memkernel"
    ]["env"]
    words = shlex.split(_codex_hook()["command"])
    assert words[0] == "env"
    assignments = dict(word.split("=", 1) for word in words[1:] if "=" in word)
    assert assignments == server_env


def test_codex_instructions_skip_recall_only_when_the_hook_block_is_shown() -> None:
    """An installed hook can inject nothing (not yet trusted, or memkernel failed): key on the block itself."""
    text = (TEMPLATES / "codex" / "AGENTS.md").read_text(encoding="utf-8")
    assert all(heading.startswith(f"## {RECOVERED}") for heading in (HEADING_SESSION_START, HEADING_POST_COMPACT))
    assert f'"{RECOVERED}"' in text


@pytest.mark.parametrize(
    ("stdio", "http", "url_key"),
    [
        ("cursor/mcp.json", "cursor/mcp.http.json", "url"),
        ("antigravity/mcp_config.json", "antigravity/mcp_config.http.json", "serverUrl"),
    ],
)
def test_json_registrations_over_stdio_and_http(stdio: str, http: str, url_key: str) -> None:
    server = json.loads((TEMPLATES / stdio).read_text(encoding="utf-8"))["mcpServers"]["memkernel"]
    assert server["command"] == "memkernel" and "MEMKERNEL_CHROMA_PERSIST_PATH" in server["env"]
    remote = json.loads((TEMPLATES / http).read_text(encoding="utf-8"))["mcpServers"]["memkernel"]
    assert remote[url_key] == "http://127.0.0.1:8765/mcp"


def test_cursor_rule_always_applies_and_antigravity_rule_is_always_on() -> None:
    """D3: the instruction, not a hook, for Cursor and Antigravity."""
    cursor = TEMPLATES / "cursor" / "rules" / "memkernel.mdc"
    assert _frontmatter(cursor)["alwaysApply"] == "true" and _frontmatter(cursor)["description"]
    antigravity = TEMPLATES / "antigravity" / "rules" / "memkernel.md"
    assert _frontmatter(antigravity)["trigger"] == "always_on"
    assert not (TEMPLATES / "cursor" / "hooks.json").exists()
    assert not (TEMPLATES / "antigravity" / "hooks.json").exists()


@pytest.mark.parametrize("path", ["codex/AGENTS.md", "cursor/rules/memkernel.mdc", "antigravity/rules/memkernel.md"])
def test_every_instruction_file_recalls_the_checkpoint_and_links_the_wiki_workflow(path: str) -> None:
    text = (TEMPLATES / path).read_text(encoding="utf-8")
    assert FIRST_RECALL in text and 'tier="long_term"' in text
    assert "WIKI_MAINTAINER.md" in text  # the wiki workflow lives in one place (#86)
    assert "<stored-memory>" in text  # stored text is data (#85)


@pytest.mark.parametrize(
    "path",
    [
        "codex/AGENTS.md",
        "cursor/rules/memkernel.mdc",
        "antigravity/rules/memkernel.md",
        "kiro/steering/memory.md",
        "claude-memory-instructions.md",
    ],
)
def test_the_instructions_say_which_ids_carry_a_checkpoint(path: str) -> None:
    """memkernel-0-15-harness-foundations B4: tools sharing work share a task (or agent) id; project is the handoff."""
    text = (TEMPLATES / path).read_text(encoding="utf-8")
    assert "MEMKERNEL_TASK_ID" in text and "MEMKERNEL_AGENT_ID" in text and 'scope="project"' in text

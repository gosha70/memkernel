#!/usr/bin/env python3
# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""Scripted stand-in for ``claude -p`` used by ``runner.py demo`` (FR-014). No model call.

It accepts the same flags the runner passes, prints stream-json events, and
simulates exactly what the demo checks: an init event (MCP connected when an
MCP config is given), one Read, a NOTES.md written into the workspace, a
store marker when MEMKERNEL_CHROMA_PERSIST_PATH is set, a wiki page on
``[wiki-export]``, an ANSWER.txt on ``[answer]``, and for ``/compact`` the
PreCompact hooks, a compact_boundary event and the PostCompact hooks taken
from the --settings file. It does not prove that Claude Code compacts.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def _flag(argv: list[str], name: str) -> str | None:
    return argv[argv.index(name) + 1] if name in argv else None


def _emit(event: dict[str, object]) -> None:
    print(json.dumps(event), flush=True)


def _run_hooks(settings: str | None, event: str) -> None:
    if not settings:
        return
    hooks = json.loads(Path(settings).read_text(encoding="utf-8")).get("hooks", {})
    for group in hooks.get(event, []):
        for hook in group.get("hooks", []):
            subprocess.run(
                hook["command"],
                shell=True,
                input=json.dumps({"hook_event_name": event}),
                text=True,
                capture_output=True,
                check=False,
            )


def main(argv: list[str]) -> int:
    prompt = _flag(argv, "-p") or ""
    settings = _flag(argv, "--settings")
    session_id = _flag(argv, "--session-id") or _flag(argv, "--resume") or "stub"
    servers = []
    if "--mcp-config" in argv:
        config = json.loads(Path(str(_flag(argv, "--mcp-config"))).read_text(encoding="utf-8"))
        servers = [{"name": name, "status": "connected"} for name in config.get("mcpServers", {})]
    if "--session-id" in argv:
        _run_hooks(settings, "SessionStart")
    _emit({"type": "system", "subtype": "init", "session_id": session_id, "mcp_servers": servers})
    usage = {"input_tokens": 10, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0, "output_tokens": 5}
    if prompt == "/compact":
        _run_hooks(settings, "PreCompact")
        _emit({"type": "system", "subtype": "compact_boundary"})
        _run_hooks(settings, "PostCompact")
        _emit({"type": "result", "subtype": "success", "result": "", "usage": usage})
        return 0
    cwd = Path.cwd()
    _emit(
        {
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "tool_use", "id": "t1", "name": "Read", "input": {"file_path": str(cwd / "README.md")}}
                ]
            },
        }
    )
    _emit({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "t1", "content": "readme"}]}})
    (cwd / "NOTES.md").write_text("stub notes\n", encoding="utf-8")
    store = os.environ.get("MEMKERNEL_CHROMA_PERSIST_PATH")
    if store:
        Path(store, "stub-store-marker").write_text("stored\n", encoding="utf-8")
    if "[wiki-export]" in prompt:
        page = cwd / "knowledge" / "wiki" / "decisions" / "demo.md"
        page.parent.mkdir(parents=True, exist_ok=True)
        page.write_text("---\npage_type: decision\n---\n# Demo\n", encoding="utf-8")
    if "[answer]" in prompt:
        (cwd / "ANSWER.txt").write_text("42\n", encoding="utf-8")
    _emit({"type": "result", "subtype": "success", "result": "done", "usage": usage})
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

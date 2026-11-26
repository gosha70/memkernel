#!/usr/bin/env python3
# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""Scripted stand-in for ``claude -p`` used by ``runner.py demo`` (FR-014). No model call.

It accepts the same flags the runner passes, prints stream-json events, and
simulates exactly what the demo checks: an init event (MCP connected when an
MCP config is given), one Read, a NOTES.md written into the workspace, a
store marker when MEMKERNEL_CHROMA_PERSIST_PATH is set, a wiki page on
``[wiki-export]``, an ANSWER.txt on ``[answer]``, a PROBE.json on ``[probe]`` (what it could reach outside its
session: the blinding check of the #90 review), and for ``/compact`` the
PreCompact hooks, a compact_boundary event and the PostCompact hooks taken
from the --settings file. It does not prove that Claude Code compacts.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

COMPACT_PRE_TOKENS = 1000  # the stub compaction call's input, reported only in compact_boundary
IMAGE_ORACLES = "/opt/memkernel/eval/lifecycle-suite/oracles"  # where the image keeps the hidden answers


def _listing(path: Path | str) -> list[str] | str:
    try:
        return sorted(os.listdir(path))
    except OSError as exc:
        return f"unreadable ({exc.errno})"


def _linger(detached: bool) -> int:
    """Start a process that would outlive the session if nothing killed it; return its pid."""
    child = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(600)"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=detached,  # detached: its own session, out of reach of a process-group kill
    )
    return child.pid


def probe(cwd: Path) -> dict[str, object]:
    """What a curious agent could reach from its working directory: its session folder's siblings, the run
    directory above them, session 0 of its chain at ``../../s0``, and the image's oracles; and two processes left
    running (one in the session's process group, one detached) that must not survive the session."""
    return {
        "lingering": {"in_group": _linger(False), "detached": _linger(True)},
        "cwd": str(cwd),
        "sessions": _listing(cwd.parent.parent),
        "run_dir": _listing(cwd.parent.parent.parent),
        "s0_reachable": (cwd / ".." / ".." / "s0").exists(),
        "oracles": _listing(IMAGE_ORACLES),
    }


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
        # as the real CLI: the boundary carries the compaction call's input, the step's result reports 0 tokens
        _emit({"type": "system", "subtype": "compact_boundary", "compact_metadata": {"pre_tokens": COMPACT_PRE_TOKENS}})
        _run_hooks(settings, "PostCompact")
        _emit({"type": "result", "subtype": "success", "result": "", "usage": dict.fromkeys(usage, 0)})
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
    if "[probe]" in prompt:
        (cwd / "PROBE.json").write_text(json.dumps(probe(cwd)), encoding="utf-8")
    _emit({"type": "result", "subtype": "success", "result": "done", "usage": usage})
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

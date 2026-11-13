# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""A small Claude Code transcript reader for the repeated-mistake count (memkernel-0-10-recall-log FR-006).

Temporary: #59 Phase 2 plans a transcript reader for each coding tool; this one is replaced when it exists. It reads
the JSON-lines files Claude Code writes under ``~/.claude/projects/<project>/``, groups their lines by
``sessionId``, and keeps only what the count needs: each session's window, its own ``Bash`` output, and its calls
to memkernel's ``recall`` tool. The format is Claude Code's own and undocumented; unreadable lines are skipped.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

COMMAND_TOOLS = frozenset({"Bash"})  # tools whose result is the session's own command output


@dataclass
class Output:
    time: datetime
    text: str


@dataclass
class RecallCall:
    time: datetime
    query: str


@dataclass
class Session:
    session_id: str
    start: datetime
    end: datetime
    outputs: list[Output] = field(default_factory=list)
    recalls: list[RecallCall] = field(default_factory=list)


def _time(entry: dict[str, Any]) -> datetime | None:
    try:
        return datetime.fromisoformat(str(entry["timestamp"]).replace("Z", "+00:00"))
    except (KeyError, ValueError):
        return None


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(str(part.get("text", "")) for part in content if isinstance(part, dict))
    return ""


def read_sessions(folder: Path, recall_tool: str) -> list[Session]:
    """Every session in ``folder``'s ``*.jsonl`` files, oldest first; ``recall_tool`` names memkernel's recall tool."""
    sessions: dict[str, Session] = {}
    tool_names: dict[str, str] = {}
    for path in sorted(folder.glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            when = _time(entry) if isinstance(entry, dict) else None
            session_id = entry.get("sessionId") if isinstance(entry, dict) else None
            if when is None or not session_id:
                continue
            session = sessions.setdefault(session_id, Session(session_id, when, when))
            session.start, session.end = min(session.start, when), max(session.end, when)
            message = entry.get("message")
            content = message.get("content") if isinstance(message, dict) else None
            if not isinstance(content, list):
                continue
            for part in content:
                if not isinstance(part, dict):
                    continue
                if part.get("type") == "tool_use":
                    tool_names[str(part.get("id"))] = str(part.get("name"))
                    if part.get("name") == recall_tool:
                        session.recalls.append(RecallCall(when, str((part.get("input") or {}).get("query", ""))))
                elif (
                    part.get("type") == "tool_result" and tool_names.get(str(part.get("tool_use_id"))) in COMMAND_TOOLS
                ):
                    session.outputs.append(Output(when, _text(part.get("content"))))
    return sorted(sessions.values(), key=lambda s: s.start)

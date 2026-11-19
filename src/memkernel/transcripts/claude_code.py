# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""Claude Code's transcripts (memkernel-0-12-capture-core FR-004; graduated from the #120 count's reader).

Claude Code writes one JSON-lines file per session under ``~/.claude/projects/<project>/``, and each subagent's
lines under ``<sessionId>/subagents/`` (workflow agents one level deeper), marked ``isSidechain`` and carrying the
parent's ``sessionId`` and the agent's ``agentId``. A tool call is a ``tool_use`` part (``id``, ``name``,
``input``); its result is a ``tool_result`` part of a later entry (``tool_use_id``, ``content``, ``is_error``),
and one entry can hold several results. The format is Claude Code's own and undocumented: an unreadable line or
part is skipped, so a format change yields fewer steps, never wrong ones.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import TYPE_CHECKING, Any

from memkernel.core.models import ToolStep, TranscriptSession, TranscriptTooLargeError

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

SUBAGENTS_DIR = "subagents"
AGENT_FILE_PREFIX = "agent-"
TRANSCRIPT_SUFFIX = ".jsonl"


class ClaudeCodeTranscriptReader:
    """``TranscriptReaderPort`` for Claude Code."""

    def read(
        self, path: Path, include_sidechains: bool = False, max_bytes: int | None = None
    ) -> list[TranscriptSession]:
        """Every session in ``path``, oldest first (FR-004).

        In a subagent file a line without ``sessionId`` belongs to the session its folder names, and a line without
        ``agentId`` to the agent the file name names (R15). A sidechain line with no agent identity at all is skipped,
        so it never joins the main thread or another agent's thread (R12).
        """
        with path.open("rb") as handle:
            data = handle.read(max_bytes + 1) if max_bytes is not None else handle.read()
        if max_bytes is not None and len(data) > max_bytes:
            raise TranscriptTooLargeError(f"{path}: larger than {max_bytes} bytes")
        folder_session, file_agent = _subagent_identity(path)
        sessions: dict[str, TranscriptSession] = {}
        calls: dict[str, ToolStep] = {}
        for line in data.decode("utf-8", errors="replace").splitlines():
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(entry, dict):
                continue
            when = _time(entry)
            session_id = str(entry.get("sessionId") or folder_session)
            if when is None or not session_id:
                continue
            session = sessions.setdefault(session_id, TranscriptSession(session_id=session_id, start=when, end=when))
            session.start, session.end = min(session.start, when), max(session.end, when)
            sidechain = entry.get("isSidechain") is True or bool(file_agent)
            if sidechain and not include_sidechains:
                continue
            agent_id = str(entry.get("agentId") or file_agent) if sidechain else ""
            if sidechain and not agent_id:
                continue  # no agent identity: it can be neither the main thread nor a known subagent (R12)
            for part in _parts(entry):
                if part.get("type") == "tool_use" and part.get("id"):
                    step = _call(part, when, sidechain, agent_id)
                    calls[step.tool_use_id] = step
                    session.steps.append(step)
                elif part.get("type") == "tool_result" and str(part.get("tool_use_id")) in calls:
                    _fill(calls[str(part.get("tool_use_id"))], part, entry, when)
        return sorted(sessions.values(), key=lambda s: s.start)


def transcript_files(folder: Path) -> Iterator[Path]:
    """A project folder's session files, then every subagent file under ``<sessionId>/subagents/``, workflow agents
    included; other files there (a workflow's ``journal.jsonl``) are not transcripts (R15)."""
    yield from sorted(folder.glob(f"*{TRANSCRIPT_SUFFIX}"))
    yield from sorted(folder.glob(f"*/{SUBAGENTS_DIR}/**/{AGENT_FILE_PREFIX}*{TRANSCRIPT_SUFFIX}"))


def _subagent_identity(path: Path) -> tuple[str, str]:
    """For a file under ``<sessionId>/subagents/``: that session id and the whole file name after ``agent-``."""
    parts = path.parts
    if SUBAGENTS_DIR not in parts[:-1] or not path.name.startswith(AGENT_FILE_PREFIX):
        return "", ""
    index = len(parts) - 1 - parts[::-1].index(SUBAGENTS_DIR)
    return (parts[index - 1] if index > 0 else ""), path.name[len(AGENT_FILE_PREFIX) : -len(TRANSCRIPT_SUFFIX)]


def _time(entry: dict[str, Any]) -> datetime | None:
    try:
        when = datetime.fromisoformat(str(entry["timestamp"]).replace("Z", "+00:00"))
    except (KeyError, ValueError):
        return None
    return when if when.tzinfo is not None else None


def _parts(entry: dict[str, Any]) -> list[dict[str, Any]]:
    message = entry.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    return [part for part in content if isinstance(part, dict)] if isinstance(content, list) else []


def _call(part: dict[str, Any], when: datetime, sidechain: bool, agent_id: str) -> ToolStep:
    raw = part.get("input")
    tool_input: dict[str, Any] = raw if isinstance(raw, dict) else {}
    return ToolStep(
        tool_use_id=str(part["id"]),
        time=when,
        tool=str(part.get("name", "")),
        command=str(tool_input.get("command", "")),
        file_path=str(tool_input.get("file_path", "")),
        query=str(tool_input.get("query", "")),
        tool_input=tool_input,
        sidechain=sidechain,
        agent_id=agent_id,
    )


def _fill(step: ToolStep, part: dict[str, Any], entry: dict[str, Any], when: datetime) -> None:
    step.uuid = str(entry.get("uuid", ""))
    step.time = when
    step.has_result = True
    step.is_error = part.get("is_error") is True  # absent means false
    step.denied = "toolDenialKind" in entry
    step.result = _text(part.get("content"))
    structured = entry.get("toolUseResult")  # an AskUserQuestion call's questions and answers (FR-001)
    if isinstance(structured, dict) and isinstance(structured.get("answers"), dict):
        questions = structured.get("questions")
        step.questions = [q for q in questions if isinstance(q, dict)] if isinstance(questions, list) else []
        step.answers = {str(k): str(v) for k, v in structured["answers"].items()}


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(str(part.get("text", "")) for part in content if isinstance(part, dict))
    return ""

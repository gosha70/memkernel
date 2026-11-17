# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""The Claude Code transcript reader (memkernel-0-12-capture-core FR-004, R2, R7, R12, R15)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from memkernel.core.models import TranscriptTooLargeError
from memkernel.core.ports import TranscriptReaderPort
from memkernel.transcripts.claude_code import ClaudeCodeTranscriptReader, transcript_files

pytestmark = pytest.mark.unit

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "transcripts"
READER = ClaudeCodeTranscriptReader()


def _entry(session: str, ts: str, content: list[Any], **extra: Any) -> str:
    return json.dumps({"sessionId": session, "timestamp": ts, "message": {"content": content}, **extra})


def _use(call: str, command: str, name: str = "Bash") -> dict[str, Any]:
    return {"type": "tool_use", "id": call, "name": name, "input": {"command": command}}


def _result(call: str, text: Any, error: bool | None = None) -> dict[str, Any]:
    part: dict[str, Any] = {"type": "tool_result", "tool_use_id": call, "content": text}
    if error is not None:
        part["is_error"] = error
    return part


def test_the_reader_implements_the_port() -> None:
    assert isinstance(READER, TranscriptReaderPort)


def test_the_real_fixture_reads_as_a_failure_an_edit_and_a_pass() -> None:
    (session,) = READER.read(FIXTURES / "failed-then-fixed.jsonl")
    assert session.session_id.startswith("4f9578ae")
    fail, edit, passed = session.steps
    assert (fail.tool, fail.is_error, fail.result.startswith("Exit code 1")) == ("Bash", True, True)
    assert (edit.tool, edit.file_path.endswith("test_zz_us1_scratch.py"), edit.is_error) == ("Edit", True, False)
    assert (passed.tool, passed.is_error, passed.has_result) == ("Bash", False, True)
    assert fail.command == passed.command and fail.uuid and fail.tool_use_id != passed.tool_use_id
    assert not any(s.sidechain or s.agent_id for s in session.steps)


def test_a_denial_and_a_blocked_call_are_errors_that_never_ran() -> None:
    (session,) = READER.read(FIXTURES / "not-captured.jsonl")
    denied, exit_zero, blocked = session.steps
    assert denied.denied and denied.is_error
    assert not exit_zero.is_error and "Traceback" in exit_zero.result
    assert blocked.is_error and blocked.result.startswith("<tool_use_error>") and not blocked.denied


def test_results_batched_in_one_entry_share_its_uuid_but_not_their_call_ids(tmp_path: Path) -> None:
    path = tmp_path / "s.jsonl"
    path.write_text(
        "\n".join(
            [
                _entry("s", "2026-11-17T10:00:00Z", [_use("a", "make a"), _use("b", "make b")]),
                _entry("s", "2026-11-17T10:00:01Z", [_result("a", "Exit code 1", True), _result("b", "ok")], uuid="u1"),
            ]
        ),
        encoding="utf-8",
    )
    (session,) = READER.read(path)
    a, b = session.steps
    assert a.uuid == b.uuid == "u1" and (a.tool_use_id, b.tool_use_id) == ("a", "b")
    assert (a.is_error, b.is_error) == (True, False)  # an absent is_error is false


def test_sidechain_lines_are_read_only_when_asked_and_carry_their_agent(tmp_path: Path) -> None:
    path = tmp_path / "s.jsonl"
    path.write_text(
        "\n".join(
            [
                _entry("s", "2026-11-17T10:00:00Z", [_use("m", "ls")]),
                _entry("s", "2026-11-17T10:00:01Z", [_use("x", "npm test")], isSidechain=True, agentId="ag1"),
            ]
        ),
        encoding="utf-8",
    )
    assert [s.tool_use_id for s in READER.read(path)[0].steps] == ["m"]
    steps = READER.read(path, include_sidechains=True)[0].steps
    assert [(s.tool_use_id, s.sidechain, s.agent_id) for s in steps] == [("m", False, ""), ("x", True, "ag1")]


def test_a_subagent_file_falls_back_to_its_folder_and_file_name(tmp_path: Path) -> None:
    folder = tmp_path / "parent-session" / "subagents" / "workflows" / "wf_1"
    folder.mkdir(parents=True)
    path = folder / "agent-review-abc.jsonl"
    line = json.dumps({"timestamp": "2026-11-17T10:00:00Z", "message": {"content": [_use("x", "pytest")]}})
    path.write_text(line + "\n", encoding="utf-8")
    (session,) = READER.read(path, include_sidechains=True)
    assert session.session_id == "parent-session"
    assert [(s.sidechain, s.agent_id) for s in session.steps] == [(True, "review-abc")]


def test_transcript_files_include_subagents_and_workflow_agents_but_not_journals(tmp_path: Path) -> None:
    for name in ("s1.jsonl", "s1/subagents/agent-a.jsonl", "s1/subagents/workflows/wf_1/agent-b.jsonl"):
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text("", encoding="utf-8")
    (tmp_path / "s1/subagents/workflows/wf_1/journal.jsonl").write_text("", encoding="utf-8")
    found = [p.relative_to(tmp_path).as_posix() for p in transcript_files(tmp_path)]
    assert found == ["s1.jsonl", "s1/subagents/agent-a.jsonl", "s1/subagents/workflows/wf_1/agent-b.jsonl"]


def test_a_file_larger_than_max_bytes_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "s.jsonl"
    path.write_text(_entry("s", "2026-11-17T10:00:00Z", [_use("a", "ls")]) + "\n", encoding="utf-8")
    with pytest.raises(TranscriptTooLargeError):
        READER.read(path, max_bytes=10)
    assert READER.read(path, max_bytes=10_000)[0].steps


def test_unreadable_lines_and_parts_are_skipped(tmp_path: Path) -> None:
    path = tmp_path / "s.jsonl"
    path.write_text(
        "\n".join(
            [
                "not json",
                json.dumps(["a list"]),
                json.dumps({"sessionId": "s", "timestamp": "2026-11-17T10:00:00"}),  # no timezone
                _entry("s", "2026-11-17T10:00:00Z", ["text", {"type": "tool_use"}, _use("a", "ls")]),
                _entry("s", "2026-11-17T10:00:01Z", [_result("unknown-call", "x"), _result("a", [{"text": "ok"}])]),
            ]
        ),
        encoding="utf-8",
    )
    (session,) = READER.read(path)
    assert [(s.tool_use_id, s.result) for s in session.steps] == [("a", "ok")]

# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""Capture: failed-then-fixed commands from ended sessions' transcripts (memkernel-0-12-capture-core)."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import chromadb
import pytest

from memkernel import capture, session_spool
from memkernel.config import MemKernelSettings
from memkernel.core.models import (
    CAPTURE_CALL_TAG,
    CAPTURE_ORIGIN_TAG,
    CAPTURE_VERSION_TAG,
    MemoryTier,
    MemoryType,
    ToolStep,
    TranscriptSession,
)
from memkernel.factory import build_service
from memkernel.lifecycle import HEADING_PREVIOUS_SESSIONS, HEADING_SESSION_START, STORED_OPEN, MemoryLifecycle
from memkernel.transcripts.claude_code import ClaudeCodeTranscriptReader
from tests.conftest import MockEmbedding

pytestmark = pytest.mark.unit

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "transcripts"
T0 = datetime(2026, 11, 17, 10, 0, tzinfo=UTC)


# ── helpers ────────────────────────────────────────────────────────────────


def _step(call: str, command: str, result: str | None, error: bool = False, **extra: Any) -> ToolStep:
    return ToolStep(
        tool_use_id=call,
        time=T0,
        tool=extra.pop("tool", "Bash"),
        command=command,
        has_result=result is not None,
        is_error=error,
        result=result or "",
        **extra,
    )


def _fail(call: str, command: str, text: str = "Error: boom") -> ToolStep:
    return _step(call, command, f"Exit code 1\n{text}", error=True)


def _pass(call: str, command: str) -> ToolStep:
    return _step(call, command, "ok")


def _session(*steps: ToolStep) -> TranscriptSession:
    return TranscriptSession(session_id="s", start=T0, end=T0, steps=list(steps))


class Transcripts:
    """Writes Claude Code transcript files and their spool lines."""

    def __init__(self, root: Path, settings: MemKernelSettings) -> None:
        self.root, self.settings, self.calls = root, settings, 0

    def session(self, session_id: str, pairs: list[tuple[str, str, bool]], ended: datetime | None = None) -> Path:
        """``pairs``: (command, result, is_error) per Bash run; the transcript and both spool lines."""
        path = self.root / f"{session_id}.jsonl"
        lines = []
        for command, result, error in pairs:
            self.calls += 1
            call = f"{session_id}-c{self.calls}"
            use = {"type": "tool_use", "id": call, "name": "Bash", "input": {"command": command}}
            res = {"type": "tool_result", "tool_use_id": call, "content": result, "is_error": error}
            lines.append({"sessionId": session_id, "timestamp": "2026-11-17T10:00:00Z", "message": {"content": [use]}})
            lines.append(
                {
                    "sessionId": session_id,
                    "uuid": f"u{self.calls}",
                    "timestamp": "2026-11-17T10:00:01Z",
                    "message": {"content": [res]},
                }
            )
        path.write_text("".join(json.dumps(line) + "\n" for line in lines), encoding="utf-8")
        self.spool(session_id, path, ended)
        return path

    def spool(self, session_id: str, path: Path | str, ended: datetime | None = None) -> None:
        end = ended or datetime.now(UTC) - timedelta(hours=1)
        session_spool.append(self.settings, session_spool.EVENT_STARTED, session_id, end - timedelta(minutes=30))
        session_spool.append(
            self.settings, session_spool.EVENT_ENDED, session_id, end, reason="other", transcript_path=str(path)
        )


FIXED = [
    ("pytest -q", "Exit code 1\nFAILED tests/test_a.py::test_x - AssertionError", True),
    ("pytest -q", "1 passed", False),
]


def _setup(tmp_path: Path, **overrides: Any) -> tuple[MemoryLifecycle, Any, Transcripts]:
    base: dict[str, Any] = {
        "project_id": f"cap-{uuid.uuid4().hex[:8]}",
        "chroma_persist_path": str(tmp_path / "chroma"),
        "state_dir": str(tmp_path / "state"),
        "capture": True,
    }
    base.update(overrides)
    settings = MemKernelSettings(**base)
    svc = build_service(settings, embedding=MockEmbedding(), chroma_client=chromadb.EphemeralClient())
    folder = tmp_path / "transcripts"
    folder.mkdir(exist_ok=True)
    return MemoryLifecycle(svc, settings), svc, Transcripts(folder, settings)


def _captured(svc: Any) -> list[Any]:
    return [m for m in svc.list_memories(include_superseded=True) if CAPTURE_ORIGIN_TAG in m.tags]


def _spooled_sessions(settings: MemKernelSettings) -> set[str]:
    path = session_spool.spool_path(settings)
    if path is None or not path.exists():
        return set()
    return {json.loads(line)["session_id"] for line in path.read_text(encoding="utf-8").splitlines()}


class SpyReader:
    def __init__(self) -> None:
        self.paths: list[Path] = []

    def read(self, path: Path, include_sidechains: bool = False, max_bytes: int | None = None) -> list[Any]:
        self.paths.append(path)
        return ClaudeCodeTranscriptReader().read(path, include_sidechains, max_bytes)


# ── D7 and FR-005 rules ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("command", "key", "own"),
    [
        ("pytest  -q", "pytest -q", True),
        ("pytest -q 2>&1 | tail -20", "pytest -q", False),
        ("pytest -q | grep FAIL | head -3", "pytest -q", False),
        ("set -o pipefail && pytest -q 2>&1 | tail -20", "set -o pipefail && pytest -q", True),
        ("set -euo pipefail; make | tail -1", "set -euo pipefail; make", True),
        ("make 2>&1", "make", True),
        ("git status -sb | head -3 && make", "git status -sb | head -3 && make", True),
    ],
)
def test_rerun_key_and_own_exit(command: str, key: str, own: bool) -> None:
    assert capture.rerun_key(command) == key
    assert capture.own_exit(command) is own


def test_the_real_fixture_yields_one_record_with_the_fr005_content() -> None:
    (session,) = ClaudeCodeTranscriptReader().read(FIXTURES / "failed-then-fixed.jsonl")
    (signal,) = capture.extract(session)
    fail = session.steps[0]
    assert signal.call == fail.tool_use_id
    assert signal.content.startswith(f"Command `{capture.stored_text(fail.command)}` failed: `")
    edit = session.steps[1]
    assert signal.content.endswith(f"after: {edit.file_path}.")  # R16: the path is kept whole


def test_the_fixtures_still_hold_the_failure_and_the_passing_rerun() -> None:
    (session,) = ClaudeCodeTranscriptReader().read(FIXTURES / "failed-then-fixed.jsonl")
    assert session.steps[0].result.startswith("Exit code 1") and session.steps[0].is_error
    assert session.steps[-1].has_result and not session.steps[-1].is_error


def test_the_not_captured_fixture_yields_nothing() -> None:
    (session,) = ClaudeCodeTranscriptReader().read(FIXTURES / "not-captured.jsonl")
    assert capture.extract(session) == []


@pytest.mark.parametrize(
    ("steps", "calls"),
    [
        ([_fail("a", "make")], []),
        ([_fail("a", "make"), _pass("b", "make"), _fail("c", "make"), _pass("d", "make")], ["a", "c"]),
        ([_fail("a", "make"), _fail("b", "make"), _pass("c", "make")], ["b"]),
        ([_fail("a", "make"), _pass("b", "make | tail -5")], []),  # the pass's status is tail's
        ([_fail("a", "make"), _pass("b", "set -o pipefail && make | tail -5")], []),  # another command
        ([_fail("a", "set -o pipefail && make | tail -5"), _pass("b", "set -o pipefail && make")], ["a"]),
        ([_fail("a", "make 2>&1 | tail -20"), _pass("b", "make")], []),  # the failure's status was tail's
        ([_fail("a", "make | grep X"), _pass("b", "make | grep X"), _pass("c", "make")], []),  # grep's exit 1
        ([_fail("a", "set -o pipefail; make | grep X"), _pass("b", "set -o pipefail; make")], ["a"]),
        ([_step("a", "make", "Exit code 1\nError", error=True, denied=True), _pass("b", "make")], []),
        ([_step("a", "make", "<tool_use_error>Blocked</tool_use_error>", error=True), _pass("b", "make")], []),
        ([_step("a", "make", "Traceback ... Error", error=False), _pass("b", "make")], []),  # exit 0
        ([_fail("a", "make"), _step("b", "make", None)], []),  # no result: neither
        ([_fail("a", "make"), _pass("b", "make  ")], ["a"]),  # whitespace collapsed
    ],
)
def test_failures_and_passes(steps: list[ToolStep], calls: list[str]) -> None:
    assert [s.call for s in capture.extract(_session(*steps))] == calls


def test_a_sidechain_failure_is_not_captured() -> None:
    steps = [_step("a", "make", "Exit code 1\nError: x", error=True, sidechain=True, agent_id="ag"), _pass("b", "make")]
    assert capture.extract(_session(*steps)) == []


def test_fix_steps_name_commands_and_edited_files_and_are_capped() -> None:
    between = [_step(f"e{i}", "", "ok", tool="Edit", file_path=f"src/f{i}.py") for i in range(7)]
    content = capture.extract(_session(_fail("a", "make", "Error: x"), *between, _pass("b", "make")))[0].content
    assert content == (
        "Command `make` failed: `Error: x`. It passed later in the same session, after: "
        "src/f0.py; src/f1.py; src/f2.py; src/f3.py; src/f4.py."
    )
    alone = capture.extract(_session(_fail("a", "make", "Error: x"), _pass("b", "make")))[0].content
    assert alone.endswith("after: no other step.")


def test_fields_are_one_line_without_backticks_and_cut() -> None:
    content = capture.extract(
        _session(_fail("a", "echo `x`\n" + "y" * 400, "Error: `q`"), _pass("b", "echo `x`\n" + "y" * 400))
    )
    (signal,) = content
    command = signal.content.split("`")[1]
    assert "\n" not in command and len(command) == capture.CAPTURE_TEXT_MAX and "`" not in command
    assert "failed: `Error: q`." in signal.content


@pytest.mark.parametrize(
    ("text", "secret"),
    [
        ("export API_KEY=abc123def", "abc123def"),
        ("DB_PASSWORD='hunter2'", "hunter2"),
        ("curl -H 'Authorization: Bearer xyz.abc'", "Bearer xyz.abc"),
        ("token AKIAABCDEFGHIJKLMNOP here", "AKIAABCDEFGHIJKLMNOP"),
        ("ghp_" + "a1" * 12, "ghp_" + "a1" * 12),
        ("gho_" + "b2" * 12, "gho_" + "b2" * 12),
        ("github_pat_" + "c3" * 12, "github_pat_" + "c3" * 12),
        ("sk-" + "d4" * 10, "sk-" + "d4" * 10),
        ("xoxb-1234567890-abc", "xoxb-1234567890-abc"),
        ("-----BEGIN RSA PRIVATE KEY-----\nMIIE\n-----END RSA PRIVATE KEY-----", "MIIE"),
        ("git clone https://user:s3cret@github.com/x/y", "s3cret"),
        ("blob Zm9vYmFyYmF6cXV4MTIzNDU2Nzg5MGFiY2RlZmdo end", "Zm9vYmFyYmF6cXV4MTIzNDU2Nzg5MGFiY2RlZmdo"),
    ],
)
def test_each_redaction_pattern_in_a_command_an_error_line_and_a_file_path(text: str, secret: str) -> None:
    flat = " ".join(text.split())
    content = capture.extract(
        _session(
            _fail("a", f"run {flat}", f"Error: {flat}"),
            _step("e", "", "ok", tool="Edit", file_path=f"/tmp/{flat}"),
            _pass("b", f"run {flat}"),
        )
    )[0].content
    for part in secret.split():
        assert part not in content
    assert capture.REDACTED in content


def test_git_shas_and_plain_words_are_kept() -> None:
    sha = "87bbd04014778a55751229b398f66e7d2be190fc"
    assert capture.redact(f"at {sha} in src/memkernel/capture.py") == f"at {sha} in src/memkernel/capture.py"


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ("ran `make test` and got `Error: disk full`", ["Error: disk full"]),
        ("a bare `ValueError` or `Exception`", []),
        ("`pkg.mod.FooError` alone", []),
        ("`except Exception:` still counts", ["except Exception:"]),
    ],
)
def test_a_stored_error_has_an_error_word_and_more_than_one_word(content: str, expected: list[str]) -> None:
    assert capture.signatures(content) == expected


# ── the startup run ────────────────────────────────────────────────────────


def test_startup_stores_one_keyed_record_and_commits_the_session(tmp_path: Path) -> None:
    lifecycle, svc, t = _setup(tmp_path)
    t.session("s1", FIXED)

    text = lifecycle.on_session_start("startup", session_id="now")

    (record,) = _captured(svc)
    assert record.type == MemoryType.OBSERVATION and record.tier == MemoryTier.SHORT_TERM
    assert record.session_id == "s1" and record.source == "capture"
    assert {CAPTURE_ORIGIN_TAG, "origin-session:s1", "origin-call:s1-c1", "origin-extractor:failed-then-fixed"} <= set(
        record.tags
    )
    assert f"{CAPTURE_VERSION_TAG}{capture.EXTRACTOR_VERSION}" in record.tags
    assert "Capture: 1 record(s) stored from 1 session(s)" in text
    assert "s1" not in _spooled_sessions(lifecycle._settings)


def test_with_capture_off_no_transcript_is_opened_and_the_spool_drains_as_before(tmp_path: Path) -> None:
    lifecycle, svc, t = _setup(tmp_path, capture=False)
    spy = SpyReader()
    lifecycle._transcripts = spy
    t.session("s1", FIXED)
    text = lifecycle.on_session_start("startup", session_id="now")
    assert spy.paths == [] and _captured(svc) == []
    assert _spooled_sessions(lifecycle._settings) == set()
    assert "ended without a saved checkpoint" in text


def test_with_capture_on_an_unsaved_session_is_reported_once_though_it_stays(tmp_path: Path) -> None:
    lifecycle, _, t = _setup(tmp_path)
    t.spool("s-gone", tmp_path / "missing.jsonl")
    first = lifecycle.on_session_start("startup", session_id="now")
    second = lifecycle.on_session_start("startup", session_id="now")
    assert "ended without a saved checkpoint" in first and "ended without a saved checkpoint" not in second
    assert "s-gone" in _spooled_sessions(lifecycle._settings)  # one miss so far, still kept


def test_interrupted_captures_neither_lose_nor_duplicate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    lifecycle, svc, t = _setup(tmp_path)
    t.session("s1", FIXED)
    real_commit = session_spool.commit

    def crash(*_: Any) -> None:
        raise RuntimeError("killed after the store, before the commit")

    monkeypatch.setattr(session_spool, "commit", crash)
    assert lifecycle.on_session_start("startup", session_id="now").startswith(HEADING_SESSION_START)
    assert len(_captured(svc)) == 1 and "s1" in _spooled_sessions(lifecycle._settings)
    monkeypatch.setattr(session_spool, "commit", real_commit)
    monkeypatch.setattr(capture, "EXTRACTOR_VERSION", capture.EXTRACTOR_VERSION + 1)  # retried after an upgrade
    lifecycle.on_session_start("startup", session_id="now")
    assert len(_captured(svc)) == 1 and "s1" not in _spooled_sessions(lifecycle._settings)
    lifecycle.on_session_start("startup", session_id="now")  # committed: never captured again
    assert len(_captured(svc)) == 1


def test_a_capture_killed_before_storing_stores_on_the_next_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lifecycle, svc, t = _setup(tmp_path)
    t.session("s1", FIXED)
    real = svc.retain
    monkeypatch.setattr(svc, "retain", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("killed")))
    assert lifecycle.on_session_start("startup", session_id="now").startswith(HEADING_SESSION_START)
    monkeypatch.setattr(svc, "retain", real)
    lifecycle.on_session_start("startup", session_id="now")
    assert len(_captured(svc)) == 1


def test_identical_content_from_two_sessions_is_two_records_and_the_first_is_untouched(tmp_path: Path) -> None:
    lifecycle, svc, t = _setup(tmp_path)
    t.session("s1", FIXED)
    lifecycle.on_session_start("startup", session_id="now")
    (first,) = _captured(svc)
    t.session("s2", FIXED)
    lifecycle.on_session_start("startup", session_id="now")
    records = _captured(svc)
    assert len(records) == 2 and records[0].content == records[1].content
    again = svc.get(first.ref_id, touch=False)
    assert (again.session_id, again.timestamp, again.tags) == (first.session_id, first.timestamp, first.tags)


def test_two_failures_batched_in_one_entry_give_two_records_and_a_retry_stores_only_the_missing_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lifecycle, svc, t = _setup(tmp_path)
    path = t.root / "s1.jsonl"
    entries = [
        {"type": "tool_use", "id": "a", "name": "Bash", "input": {"command": "make a"}},
        {"type": "tool_use", "id": "b", "name": "Bash", "input": {"command": "make b"}},
    ]
    results = [
        {"type": "tool_result", "tool_use_id": "a", "content": "Exit code 1\nError: a", "is_error": True},
        {"type": "tool_result", "tool_use_id": "b", "content": "Exit code 1\nError: b", "is_error": True},
    ]
    passes = [
        {"type": "tool_use", "id": i, "name": "Bash", "input": {"command": c}}
        for i, c in (("c", "make a"), ("d", "make b"))
    ]
    passed = [{"type": "tool_result", "tool_use_id": i, "content": "ok"} for i in ("c", "d")]
    lines = [
        {"sessionId": "s1", "timestamp": "2026-11-17T10:00:00Z", "message": {"content": entries}},
        {"sessionId": "s1", "uuid": "batch", "timestamp": "2026-11-17T10:00:01Z", "message": {"content": results}},
        {"sessionId": "s1", "timestamp": "2026-11-17T10:00:02Z", "message": {"content": passes}},
        {"sessionId": "s1", "uuid": "p", "timestamp": "2026-11-17T10:00:03Z", "message": {"content": passed}},
    ]
    path.write_text("".join(json.dumps(line) + "\n" for line in lines), encoding="utf-8")
    t.spool("s1", path)
    real, calls = svc.retain, []

    def second_crashes(*a: Any, **k: Any) -> str:
        calls.append(1)
        if len(calls) == 2:
            raise RuntimeError("killed after one record")
        return str(real(*a, **k))

    monkeypatch.setattr(svc, "retain", second_crashes)
    assert lifecycle.on_session_start("startup", session_id="now").startswith(HEADING_SESSION_START)
    monkeypatch.setattr(svc, "retain", real)
    lifecycle.on_session_start("startup", session_id="now")
    tags = sorted(t2 for m in _captured(svc) for t2 in m.tags if t2.startswith(CAPTURE_CALL_TAG))
    assert tags == ["origin-call:a", "origin-call:b"]


def test_another_process_holding_the_capture_lock_makes_this_start_skip(tmp_path: Path) -> None:
    lifecycle, svc, t = _setup(tmp_path)
    t.session("s1", FIXED)
    spool = session_spool.spool_path(lifecycle._settings)
    assert spool is not None
    lock = spool.with_name(capture.CAPTURE_LOCK_FILE)
    lock.parent.mkdir(parents=True, exist_ok=True)
    holder = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import fcntl,sys,time; f=open(sys.argv[1],'a'); fcntl.flock(f,fcntl.LOCK_EX); print('held',flush=True); "
            "sys.stdin.readline()",
            str(lock),
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert holder.stdout is not None and holder.stdout.readline().strip() == "held"
        lifecycle.on_session_start("startup", session_id="now")
        assert _captured(svc) == [] and "s1" in _spooled_sessions(lifecycle._settings)
    finally:
        assert holder.stdin is not None
        holder.stdin.write("\n")
        holder.stdin.close()
        holder.wait(timeout=10)
    lifecycle.on_session_start("startup", session_id="now")
    assert len(_captured(svc)) == 1


def test_signals_over_the_per_session_cap_are_dropped_and_counted(tmp_path: Path) -> None:
    lifecycle, svc, t = _setup(tmp_path)
    runs = []
    for i in range(capture.CAPTURE_SESSION_MAX_RECORDS + 1):
        runs += [(f"make t{i}", f"Exit code 1\nError: t{i}", True), (f"make t{i}", "ok", False)]
    t.session("s1", runs)
    text = lifecycle.on_session_start("startup", session_id="now")
    assert len(_captured(svc)) == capture.CAPTURE_SESSION_MAX_RECORDS
    assert "1 signal(s) over the per-session cap dropped" in text
    assert "s1" not in _spooled_sessions(lifecycle._settings)


def test_a_readable_transcript_without_the_session_is_a_miss_and_one_with_no_signal_is_committed(
    tmp_path: Path,
) -> None:
    lifecycle, svc, t = _setup(tmp_path)
    other = t.session("other", [("ls", "ok", False)])
    t.spool("s-stale", other)  # a stale path: readable, but another session's file
    t.session("s-quiet", [("ls", "ok", False)])
    lifecycle.on_session_start("startup", session_id="now")
    spooled = _spooled_sessions(lifecycle._settings)
    assert "s-stale" in spooled and "s-quiet" not in spooled and _captured(svc) == []


def test_a_missing_transcript_is_given_up_at_the_miss_limit(tmp_path: Path) -> None:
    lifecycle, _, t = _setup(tmp_path)
    t.spool("s-gone", tmp_path / "missing.jsonl")
    for _ in range(capture.CAPTURE_MISS_LIMIT - 1):
        lifecycle.on_session_start("startup", session_id="now")
        assert "s-gone" in _spooled_sessions(lifecycle._settings)
    text = lifecycle.on_session_start("startup", session_id="now")
    assert "s-gone" not in _spooled_sessions(lifecycle._settings)
    assert "1 transcript(s) given up on" in text


def test_an_oversized_transcript_is_given_up_at_once_without_being_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lifecycle, _, t = _setup(tmp_path)
    spy = SpyReader()
    lifecycle._transcripts = spy
    t.session("s-big", FIXED)
    monkeypatch.setattr(capture, "CAPTURE_TRANSCRIPT_MAX_BYTES", 10)
    text = lifecycle.on_session_start("startup", session_id="now")
    assert spy.paths == [] and "s-big" not in _spooled_sessions(lifecycle._settings)
    assert "1 transcript(s) given up on" in text


def test_the_run_record_cap_and_the_time_budget_leave_sessions_for_the_next_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lifecycle, svc, t = _setup(tmp_path)
    t.session("s1", FIXED, ended=datetime.now(UTC) - timedelta(hours=3))
    t.session("s2", FIXED, ended=datetime.now(UTC) - timedelta(hours=2))
    monkeypatch.setattr(capture, "CAPTURE_MAX_RECORDS", 1)
    text = lifecycle.on_session_start("startup", session_id="now")
    assert len(_captured(svc)) == 1 and "1 session(s) left for the next start" in text
    assert _spooled_sessions(lifecycle._settings) == {"s2"}
    monkeypatch.setattr(capture, "CAPTURE_MAX_RECORDS", 20)
    ticks = iter([0.0, capture.CAPTURE_TIME_BUDGET + 1])
    drained = session_spool.drain(lifecycle._settings, "now", lambda _w: True, keep_ended=True)
    report = capture.run(svc, lifecycle._settings, drained, ClaudeCodeTranscriptReader(), clock=lambda: next(ticks))
    assert report.left == 1 and report.stored == 0


def test_without_locking_capture_stays_off_with_one_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    import memkernel.lifecycle as lifecycle_module

    lifecycle, svc, t = _setup(tmp_path)
    spy = SpyReader()
    lifecycle._transcripts = spy
    t.session("s1", FIXED)
    monkeypatch.setattr(session_spool, "locking", lambda: False)
    monkeypatch.setattr(lifecycle_module, "_warned_capture_unlocked", False)
    lifecycle.on_session_start("startup", session_id="now")
    lifecycle.on_session_start("startup", session_id="now")
    assert spy.paths == [] and _captured(svc) == [] and _spooled_sessions(lifecycle._settings) == set()
    assert sum("no file locking" in r.message for r in caplog.records) == 1


def test_captured_records_are_never_promotion_candidates_and_are_quoted_when_shown(tmp_path: Path) -> None:
    lifecycle, svc, t = _setup(tmp_path)
    t.session("s1", FIXED)
    lifecycle.on_session_start("startup", session_id="now")
    (record,) = _captured(svc)
    for _ in range(3):
        svc.get(record.ref_id)  # recalled often: would rank first as a candidate
    assert record.ref_id not in [c["ref_id"] for c in svc.consolidate(limit=10)["candidates"]]
    (line,) = lifecycle._memory_lines([svc.get(record.ref_id, touch=False)])
    assert STORED_OPEN in line


def test_an_ended_session_kept_past_the_age_limit_is_dropped_and_counted(tmp_path: Path) -> None:
    lifecycle, _, t = _setup(tmp_path)
    t.spool("s-old", tmp_path / "missing.jsonl", ended=datetime.now(UTC) - timedelta(days=8))
    text = lifecycle.on_session_start("startup", session_id="now")
    assert "s-old" not in _spooled_sessions(lifecycle._settings)
    assert HEADING_PREVIOUS_SESSIONS in text and "1 ended session(s) were not captured within 7 days" in text


def test_commit_removes_only_the_named_sessions(tmp_path: Path) -> None:
    _, _, t = _setup(tmp_path)
    t.spool("a", "x")
    t.spool("b", "y")
    session_spool.commit(t.settings, ["a"])
    assert _spooled_sessions(t.settings) == {"b"}
    shutil.rmtree(tmp_path / "state")
    session_spool.commit(t.settings, ["b"])  # no spool: nothing to do


def test_misses_and_a_budget_stop_both_count_as_left(tmp_path: Path) -> None:
    """Review of #137, finding 4: the sessions a budget stop leaves add to the misses already counted."""
    lifecycle, svc, t = _setup(tmp_path)
    t.spool("s-gone", tmp_path / "missing.jsonl", ended=datetime.now(UTC) - timedelta(hours=4))
    t.session("s1", FIXED, ended=datetime.now(UTC) - timedelta(hours=3))
    t.session("s2", FIXED, ended=datetime.now(UTC) - timedelta(hours=2))
    drained = session_spool.drain(lifecycle._settings, "now", lambda _w: True, keep_ended=True)
    ticks = iter([0.0, 0.0, capture.CAPTURE_TIME_BUDGET + 1])
    report = capture.run(svc, lifecycle._settings, drained, ClaudeCodeTranscriptReader(), clock=lambda: next(ticks))
    assert report.left == 3 and report.stored == 0


def test_the_key_lookup_is_store_filtered_and_metadata_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Review of #137, finding 3 (FR-003)."""
    lifecycle, svc, t = _setup(tmp_path)
    svc.retain("an agent note in the same session", MemoryType.FACT, session_id="s1")
    t.session("s1", FIXED)
    seen: list[tuple[Any, bool]] = []
    real = svc._vector_store.list_all

    def spy(where: Any = None, include_content: bool = True) -> Any:
        seen.append((where, include_content))
        return real(where, include_content)

    monkeypatch.setattr(svc._vector_store, "list_all", spy)
    assert capture._captured_calls(svc, "s1") == set()
    assert seen == [({"$and": [{"session_id": "s1"}, {"source": "capture"}]}, False)]


class BrokenReader:
    def read(self, path: Path, include_sidechains: bool = False, max_bytes: int | None = None) -> list[Any]:
        raise RuntimeError("an unexpected reader failure")


def test_a_capture_failure_never_costs_the_startup_block(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """Review of #137 at 6c0072e: capture is opt-in, so its failure is logged and the block renders without it."""
    lifecycle, svc, t = _setup(tmp_path)
    svc.retain("Use Postgres for the user store.", MemoryType.DECISION)
    lifecycle._transcripts = BrokenReader()
    t.session("s1", FIXED)
    text = lifecycle.on_session_start("startup", session_id="now")
    assert text.startswith(HEADING_SESSION_START) and "Use Postgres for the user store." in text
    assert "Capture:" not in text and "s1" in _spooled_sessions(lifecycle._settings)  # retried at the next start
    assert any("capture failed" in r.message for r in caplog.records)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "FileNotFoundError: '/Users/george/projects/memkernel/specs/memkernel-0-12-capture-core/spec.md'",
            "FileNotFoundError: '/Users/george/projects/memkernel/specs/memkernel-0-12-capture-core/spec.md'",
        ),
        (
            "ERROR tests/unit/test_v2_storage/test_chroma_backend_migration.py::test_x - AssertionError: 3 != 4",
            "ERROR tests/unit/test_v2_storage/test_chroma_backend_migration.py::test_x - AssertionError: 3 != 4",
        ),
        ("blob Zm9vYmFyYmF6cXV4MTIzNDU2Nzg5MGFiY2RlZmdo end", "blob [REDACTED] end"),
        ("secret aGVsbG8gd29ybGQgdGhpcyBpcyBhIHRlc3Q/c2VjcmV0MTIzNDU2Nzg5MGFiY2Rl", "secret [REDACTED]"),
        ("at 87bbd04014778a55751229b398f66e7d2be190fc", "at 87bbd04014778a55751229b398f66e7d2be190fc"),
        ("src/tests/ChromaBackendV2Test.py", "[REDACTED].py"),  # the accepted cost: CamelCase with a digit
        ("~/work/repo2/memkernel-0-12-capture-core/file", "~/work/repo2/memkernel-0-12-capture-core/file"),
        ("k aB3dE5fG7hJ9kL1mN3pQ5rS7tU9vW1xY3z/xyz", "k [REDACTED]"),  # not path-shaped: judged whole
        ("cd specs/memkernel-0-12-capture-core", "cd [REDACTED]"),  # the stated cost, as before R16
    ],
)
def test_long_strings_are_judged_piece_by_piece(text: str, expected: str) -> None:
    """R16 (the owner's, 2026-11-17): paths keep their components, so the count can match a captured error."""
    assert capture.redact(text) == expected


def test_a_captured_error_with_a_long_path_still_matches_later_output() -> None:
    """R16: the stored error is the real text, so a later failure with the same output is a repeat."""
    error = "ERROR tests/unit/test_v2_storage/test_chroma_backend_migration.py::test_x - AssertionError: 3 != 4"
    (signal,) = capture.extract(_session(_fail("a", "pytest", error), _pass("b", "pytest")))
    (stored,) = capture.signatures(signal.content)
    assert stored == error and stored in capture.collapse(f"Exit code 1\n{error}")


@pytest.mark.parametrize(
    "text",
    [
        "key wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
        "aws configure set aws_secret_access wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY --profile x",
    ],
)
def test_the_aws_sample_secret_key_is_redacted(text: str) -> None:
    """AWS's documented sample secret key, bare and inside a command: split on "/", its pieces would all pass."""
    assert "wJalrXUtnFEMI" not in capture.redact(text) and capture.REDACTED in capture.redact(text)

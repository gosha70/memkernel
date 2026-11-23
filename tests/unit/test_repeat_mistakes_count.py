# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""The repeated-mistake count on a fixture with known repeats (memkernel-0-10-recall-log SC-3)."""

from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from memkernel import recall_log
from memkernel.config import MemKernelSettings
from memkernel.core.models import MemoryType
from memkernel.factory import build_service
from memkernel.transcripts.claude_code import ClaudeCodeTranscriptReader, transcript_files
from tests.conftest import MockEmbedding

pytestmark = pytest.mark.unit

COUNT = Path(__file__).resolve().parents[2] / "eval" / "repeat-mistakes" / "count.py"


def _load() -> Any:
    spec = importlib.util.spec_from_file_location("repeat_mistakes_count", COUNT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


count_module = _load()


class Transcript:
    """Writes Claude Code transcript lines for one session, or for one of its subagents (``agent``)."""

    def __init__(self, folder: Path, session_id: str, agent: str = "", workflow: str = "") -> None:
        if agent:
            sub = folder / session_id / "subagents" / (f"workflows/{workflow}" if workflow else "")
            sub.mkdir(parents=True, exist_ok=True)
            self.path = sub / f"agent-{agent}.jsonl"
        else:
            self.path = folder / f"{session_id}.jsonl"
        self.session_id, self.agent = session_id, agent
        self.calls = 0

    def _write(self, when: datetime, entry_type: str, content: list[dict[str, Any]]) -> None:
        entry: dict[str, Any] = {
            "type": entry_type,
            "sessionId": self.session_id,
            "timestamp": when.isoformat().replace("+00:00", "Z"),
        }
        if self.agent:
            entry.update(isSidechain=True, agentId=self.agent)
        entry["message"] = {"role": entry_type, "content": content}
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry) + "\n")

    def tool(self, when: datetime, name: str, tool_input: dict[str, Any], result: str, failed: bool = False) -> None:
        """One call and its result; ``failed``: a run that exited 1 (``is_error`` and an ``Exit code`` result)."""
        self.calls += 1
        call_id = f"{self.session_id}-{self.agent}-{self.calls}"
        part: dict[str, Any] = {"type": "tool_result", "tool_use_id": call_id, "content": result}
        if failed:
            part.update(content=f"Exit code 1\n{result}", is_error=True)
        self._write(when, "assistant", [{"type": "tool_use", "id": call_id, "name": name, "input": tool_input}])
        self._write(when, "user", [part])


def _settings(tmp_path: Path, project: str) -> MemKernelSettings:
    return MemKernelSettings(
        project_id=project,
        chroma_persist_path=str(tmp_path / f"chroma-{project}"),
        state_dir=str(tmp_path / "state"),
        recall_log=True,
    )


def _store_arg(tmp_path: Path, project: str) -> str:
    return f"name={project},chroma={tmp_path / f'chroma-{project}'},state={tmp_path / 'state'},project={project}"


def test_every_outcome_on_a_fixture_with_known_repeats(tmp_path: Path) -> None:
    a, b = _settings(tmp_path, "a"), _settings(tmp_path, "b")
    svc_a = build_service(a, embedding=MockEmbedding(dimension=384))
    svc_b = build_service(b, embedding=MockEmbedding(dimension=384))
    m_shown = svc_a.retain("npm test fails with `Error: Cannot find module 'left-pad'`", MemoryType.FACT)
    m_missed = svc_a.retain("CI said `FAILED tests/test_db.py::test_migrate` after the rename", MemoryType.FACT)
    m_unknown = svc_a.retain("Install first: `ModuleNotFoundError: No module named 'yaml'`", MemoryType.FACT)
    m_two = svc_a.retain("ran `make test` and got `Error: disk full`", MemoryType.OBSERVATION)
    m_other = svc_b.retain("Outside a checkout: `fatal: not a git repository`", MemoryType.FACT)
    m_plain = svc_a.retain("Use Postgres for the user store.", MemoryType.DECISION)
    del svc_a, svc_b

    t0 = datetime.now(UTC) + timedelta(hours=1)
    folder = tmp_path / "transcripts"
    folder.mkdir()
    tool = count_module.DEFAULT_RECALL_TOOL

    def at(minutes: float) -> datetime:
        return t0 + timedelta(minutes=minutes)

    # S1 shown: the session-start block showed the memory before the failure.
    s1 = Transcript(folder, "s1")
    recall_log.append(a, "hook", [m_shown, m_plain], session_id="s1", block="session-start", now=at(0))
    s1.tool(at(1), "Bash", {"command": "npm test"}, "Error: Cannot find module 'left-pad'\nRequire stack: ...", True)
    # S2 missed: the store was used, but the recall that returned the memory came after the failure.
    s2 = Transcript(folder, "s2")
    recall_log.append(a, "hook", [m_plain], session_id="s2", block="session-start", now=at(10))
    s2.tool(at(11), "Bash", {"command": "pytest"}, "FAILED tests/test_db.py::test_migrate  -  AssertionError", True)
    s2.tool(at(12), tool, {"query": "db migrate failure"}, "[]")
    recall_log.append(a, "tool", [m_missed], query="db migrate failure", now=at(12) + timedelta(seconds=1))
    # S3 other store: the session only used store a; the memory is in store b.
    s3 = Transcript(folder, "s3")
    recall_log.append(a, "hook", [m_plain], session_id="s3", block="session-start", now=at(20))
    s3.tool(at(21), "Bash", {"command": "git status"}, "fatal: not a git repository (or any parent)", True)
    # S4 unknown: no log records for this session.
    s4 = Transcript(folder, "s4")
    s4.tool(at(30), "Bash", {"command": "python app.py"}, "ModuleNotFoundError: No module named 'yaml'", True)
    # S5 and S6 make the same recall call at the same moment: the tool record is ambiguous and never guessed.
    s5, s6 = Transcript(folder, "s5"), Transcript(folder, "s6")
    s5.tool(at(40), tool, {"query": "disk"}, "[]")
    s6.tool(at(40), tool, {"query": "disk"}, "[]")
    recall_log.append(a, "tool", [m_two], query="disk", now=at(40))
    s5.tool(at(41), "Bash", {"command": "make test"}, "make: *** Error: disk full", True)
    # S6 reads a note that mentions an error: that is not command output, so not a repeat.
    s6.tool(at(42), "Read", {"file_path": "notes.md"}, "We once saw Error: Cannot find module 'left-pad'")
    # S7 was shown a memory and did not repeat its error.
    s7 = Transcript(folder, "s7")
    recall_log.append(a, "hook", [m_shown, m_unknown], session_id="s7", block="session-start", now=at(50))  # two
    s7.tool(at(51), "Bash", {"command": "ls"}, "README.md")

    out = tmp_path / "report.json"
    assert (
        count_module.main(
            [
                "--store",
                _store_arg(tmp_path, "a"),
                "--store",
                _store_arg(tmp_path, "b"),
                "--transcripts",
                str(folder),
                "--json",
                str(out),
            ]
        )
        == 0
    )
    report = json.loads(out.read_text(encoding="utf-8"))
    outcomes = {(d["ref_id"], d["session_id"]): d for d in report["details"]}
    assert set(outcomes) == {(m_shown, "s1"), (m_missed, "s2"), (m_other, "s3"), (m_unknown, "s4"), (m_two, "s5")}
    assert outcomes[(m_shown, "s1")]["outcome"] == "shown"
    assert outcomes[(m_missed, "s2")]["outcome"] == "missed"
    assert outcomes[(m_missed, "s2")]["evidence"] == {
        "tool_recalls_before_failure": 0,
        "hook_blocks_before_failure": 1,
        "all_tool_recalls_filtered_out": False,
    }
    assert outcomes[(m_other, "s3")]["outcome"] == "other store"
    assert outcomes[(m_unknown, "s4")]["outcome"] == "unknown"
    assert outcomes[(m_two, "s5")]["outcome"] == "unknown"
    assert outcomes[(m_two, "s5")]["signature"] == "Error: disk full"
    assert outcomes[(m_two, "s5")]["command"] == "make test"  # R8: the evidence names the command
    assert report["by_outcome"] == {"shown": 1, "missed": 1, "other store": 1, "unknown": 2}
    assert report["shown_without_repeat"] == 1  # one session, though it was shown two memories
    assert report["unattributed_tool_records"] == 1
    assert report["stored_errors"] == 5 and report["limits"]


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ("ran `make test` and got `Error: disk full`", ["Error: disk full"]),
        ("`error: lowercase` is not an error word", []),
        (
            "`FAILED  a::b`  and `Traceback (most recent call last):`",
            ["FAILED a::b", "Traceback (most recent call last):"],
        ),
        ("no backticks: Error: plain text", []),
        ("a bare `ValueError` is one word", []),  # R9
    ],
)
def test_stored_errors_are_backtick_spans_with_an_error_word(content: str, expected: list[str]) -> None:
    assert count_module.signatures(content) == expected


def _error(**overrides: Any) -> Any:
    fields: dict[str, Any] = {
        "store": "a",
        "ref_id": "r1",
        "type": "fact",
        "tier": "long_term",
        "checkpoint": False,
        "session_id": "build-1",
        "time": datetime.now(UTC),
        "signature": "Error: x",
    }
    fields.update(overrides)
    return count_module.StoredError(**fields)


@pytest.mark.parametrize(
    ("filters", "error_overrides", "excluded"),
    [
        ({"type": "decision"}, {}, True),
        ({"tier": "working"}, {}, True),
        ({"session_id_filter": "other"}, {}, True),
        ({"session_id_filter": "build-1"}, {}, False),
        ({"include_needs_review": False}, {}, False),  # whether it was flagged then is not known
        ({"checkpoint_only": True}, {}, True),
        ({"top_k": 3, "order": "relevance"}, {}, False),
    ],
)
def test_every_logged_filter_is_evaluated(
    filters: dict[str, Any], error_overrides: dict[str, Any], excluded: bool
) -> None:
    when = datetime.now(UTC)
    error = _error(**error_overrides)
    record = count_module.LogRecord("a", when, "tool", "", "q", filters, [])
    hook = count_module.LogRecord("a", when, "hook", "s", "", {}, [])
    outcome, evidence = count_module.classify(error, [record, hook], when + timedelta(seconds=1))
    assert outcome == "missed"
    assert evidence == {
        "tool_recalls_before_failure": 1,
        "hook_blocks_before_failure": 1,
        "all_tool_recalls_filtered_out": excluded,
    }


def test_a_truncated_record_makes_a_miss_unknown() -> None:
    when = datetime.now(UTC)
    cut = count_module.LogRecord("a", when, "tool", "", "", {}, ["r0"], "h", True)
    outcome, evidence = count_module.classify(_error(), [cut], when + timedelta(seconds=1))
    assert outcome == "unknown" and evidence == {"truncated_record_before_failure": True}
    shown = count_module.LogRecord("a", when, "tool", "", "", {}, ["r1"], "h", True)
    assert count_module.classify(_error(), [shown], when + timedelta(seconds=1))[0] == "shown"


def test_a_cut_query_still_pairs_by_its_hash(tmp_path: Path) -> None:
    settings = _settings(tmp_path, "a")
    query = "why does the migration fail " * 80  # 2,240 characters: longer than the log keeps
    when = datetime.now(UTC)
    recall_log.append(settings, "tool", ["r1"], query=query, now=when)
    folder = tmp_path / "t"
    folder.mkdir()
    Transcript(folder, "s1").tool(when, count_module.DEFAULT_RECALL_TOOL, {"query": query}, "[]")
    store = count_module.Store("a", settings)
    records, malformed = count_module.read_log(store)
    assert malformed == 0 and len(records[0].query) < len(query)
    by_thread, possible, unattributed = count_module.attribute(
        records, count_module.read_sessions(folder, count_module.DEFAULT_RECALL_TOOL)
    )
    assert unattributed == 0 and not possible and [r.ref_ids for r in by_thread[("s1", "")]] == [["r1"]]


def test_an_ambiguous_record_that_may_have_shown_the_memory_makes_a_miss_unknown() -> None:
    when = datetime.now(UTC)
    hook = count_module.LogRecord("a", when, "hook", "s1", "", {}, [])
    ambiguous = count_module.LogRecord("a", when, "tool", "", "q", {}, ["r1"], "h")
    failure = when + timedelta(seconds=1)
    assert count_module.classify(_error(), [hook], failure, [ambiguous]) == (
        "unknown",
        {"ambiguous_record_may_have_shown": True},
    )
    other = count_module.LogRecord("a", when, "tool", "", "q", {}, ["r9"], "h")
    assert count_module.classify(_error(), [hook], failure, [other])[0] == "missed"


@pytest.mark.parametrize(
    "line",
    [
        {"filters": []},
        {"truncated": "false"},
        {"ref_ids": "r1"},
        {"ref_ids": [1]},
        {"origin": "other"},
        {"time": "2026-11-12T10:00:00"},
        {"session_id": 7},
    ],
    ids=["filters-list", "truncated-string", "ref-ids-string", "ref-ids-int", "origin", "naive-time", "session-int"],
)
def test_a_malformed_log_line_is_skipped_and_counted(tmp_path: Path, line: dict[str, Any]) -> None:
    settings = _settings(tmp_path, "a")
    recall_log.append(settings, "tool", ["r1"], query="q")
    path = recall_log.log_path(settings)
    assert path is not None
    good = json.loads(path.read_text(encoding="utf-8"))
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({**good, **line}) + "\n")
    records, malformed = count_module.read_log(count_module.Store("a", settings))
    assert len(records) == 1 and malformed == 1


def test_a_record_that_lost_only_query_text_still_shows_a_miss(tmp_path: Path) -> None:
    settings = _settings(tmp_path, "a")
    recall_log.append(settings, "tool", ["r9"], query="é" * 1_500)  # the query is cut, the one id kept
    (record,), _ = count_module.read_log(count_module.Store("a", settings))
    assert record.truncated is False  # ids complete: the record can show the memory was not returned


def test_subagents_failed_runs_only_and_threads_on_a_fake_transcript_folder(tmp_path: Path) -> None:
    """memkernel-0-12-capture-core SC-8 (R7–R15), after DIADE's reproduction on #112."""
    a = _settings(tmp_path, "a")
    svc = build_service(a, embedding=MockEmbedding(dimension=384))
    err = "Error: Cannot find module 'x'"
    m = svc.retain(f"npm test fails with `{err}`", MemoryType.FACT)
    svc.retain("a bare `ValueError` is not a stored error", MemoryType.FACT)
    other = svc.retain("Use Postgres for the user store.", MemoryType.DECISION)
    del svc
    t0 = datetime.now(UTC) + timedelta(hours=1)
    folder = tmp_path / "transcripts"
    folder.mkdir()
    tool = count_module.DEFAULT_RECALL_TOOL

    def at(minutes: float) -> datetime:
        return t0 + timedelta(minutes=minutes)

    # B only reads a note that quotes the error: not a failed run, so not a repeat (R8).
    Transcript(folder, "B").tool(at(1), "Bash", {"command": "cat NOTES.md"}, f"- npm test fails with `{err}`")
    # D's subagent runs the failing command: a repeat for D, on the subagent line, naming the command (R7, R10).
    Transcript(folder, "D").tool(at(10), "Bash", {"command": "ls"}, "src")
    recall_log.append(a, "hook", [m], session_id="D", block="session-start", now=at(10))  # the parent was shown it
    Transcript(folder, "D", agent="sub1").tool(at(11), "Bash", {"command": "npm test 2>&1"}, err, True)
    # E's subagent recalls the memory; then E's main thread repeats: the main thread never saw it (R12).
    recall_log.append(a, "hook", [other], session_id="E", block="session-start", now=at(20))
    Transcript(folder, "E").tool(at(20), "Bash", {"command": "ls"}, "src")
    Transcript(folder, "E", agent="sub2").tool(at(21), tool, {"query": "module x"}, "[]")
    recall_log.append(a, "tool", [m], query="module x", now=at(21))
    Transcript(folder, "E").tool(at(22), "Bash", {"command": "npm test"}, err, True)
    # F's subagent recalls the memory, then repeats the error itself: shown, on the subagent line (R14).
    Transcript(folder, "F").tool(at(30), "Bash", {"command": "ls"}, "src")
    sub3 = Transcript(folder, "F", agent="sub3")
    sub3.tool(at(31), tool, {"query": "npm module"}, "[]")
    recall_log.append(a, "tool", [m], query="npm module", now=at(31))
    sub3.tool(at(32), "Bash", {"command": "npm test"}, err, True)
    # G's workflow agent fails; the workflow's journal beside it is not a transcript (R15).
    Transcript(folder, "G").tool(at(40), "Bash", {"command": "ls"}, "src")
    Transcript(folder, "G", agent="wf-agent", workflow="wf_x").tool(at(41), "Bash", {"command": "npm ci"}, err, True)
    (folder / "G" / "subagents" / "workflows" / "wf_x" / "journal.jsonl").write_text("{}\n", encoding="utf-8")

    out = tmp_path / "report.json"
    assert (
        count_module.main(["--store", _store_arg(tmp_path, "a"), "--transcripts", str(folder), "--json", str(out)]) == 0
    )
    report = json.loads(out.read_text(encoding="utf-8"))
    found = {(d["session_id"], d["agent_id"]): d for d in report["details"]}
    assert set(found) == {("D", "sub1"), ("E", ""), ("F", "sub3"), ("G", "wf-agent")}
    assert report["stored_errors"] == 1  # `ValueError` alone is not one (R9)
    assert found[("D", "sub1")]["outcome"] == "not shown" and found[("D", "sub1")]["command"] == "npm test 2>&1"
    assert found[("E", "")]["outcome"] == "missed"  # the subagent's recall is not the main thread's
    assert found[("F", "sub3")]["outcome"] == "shown"
    assert found[("G", "wf-agent")]["outcome"] == "not shown"
    assert report["repeats"] == 1 and report["by_outcome"]["missed"] == 1
    assert report["subagent_repeats"] == 3
    assert report["by_outcome_subagent"] == {"shown": 1, "not shown": 2, "other store": 0, "unknown": 0}
    rendered = count_module.render(report)
    assert "3 subagent repeat(s), reported apart" in rendered and "(subagent sub1)" in rendered
    assert "from `npm test 2>&1`" in rendered


def test_a_subagent_repeat_keeps_other_store_and_unknown() -> None:
    when = datetime.now(UTC)
    failure = when + timedelta(seconds=1)
    elsewhere = count_module.LogRecord("b", when, "tool", "", "q", {}, ["r9"], "h")
    assert count_module.classify_subagent(_error(), [elsewhere], failure)[0] == "other store"
    cut = count_module.LogRecord("a", when, "tool", "", "", {}, ["r0"], "h", True)
    assert count_module.classify_subagent(_error(), [cut], failure)[0] == "unknown"
    ambiguous = count_module.LogRecord("a", when, "tool", "", "q", {}, ["r1"], "h")
    assert count_module.classify_subagent(_error(), [], failure, [ambiguous])[0] == "unknown"
    assert count_module.classify_subagent(_error(), [], failure)[0] == "not shown"


def test_captured_errors_are_reported_apart(tmp_path: Path) -> None:
    """FR-011: a captured record's error that comes back is counted on its own line."""
    from memkernel.core.models import CAPTURE_ORIGIN_TAG

    a = _settings(tmp_path, "a")
    svc = build_service(a, embedding=MockEmbedding(dimension=384))
    svc.retain(
        "Command `make` failed: `Error: disk full`. It passed later.", MemoryType.OBSERVATION, tags=[CAPTURE_ORIGIN_TAG]
    )
    svc.retain("agent note: `Error: no space left`", MemoryType.FACT)
    del svc
    folder = tmp_path / "transcripts"
    folder.mkdir()
    when = datetime.now(UTC) + timedelta(hours=1)
    recall_log.append(a, "hook", [], session_id="s1", block="session-start", now=when)
    Transcript(folder, "s1").tool(when + timedelta(minutes=1), "Bash", {"command": "make"}, "Error: disk full", True)
    report = count_module.count(
        [count_module.parse_store(_store_arg(tmp_path, "a"))], count_module.read_sessions(folder, "x")
    )
    assert report["captured_errors"] == 1 and report["captured_repeats"] == 1
    assert report["by_outcome_captured"]["missed"] == 1 and report["details"][0]["captured"] is True
    assert "1 of the stored errors are from captured records" in count_module.render(report)


def test_only_records_before_the_failure_decide_the_outcome() -> None:
    """Review of #137, finding 1: a recall after the failure is not evidence, on either thread."""
    when = datetime.now(UTC)
    failure = when + timedelta(seconds=1)
    later_same = count_module.LogRecord("a", failure + timedelta(minutes=1), "tool", "", "q", {}, ["r9"], "h")
    assert count_module.classify(_error(), [later_same], failure) == ("unknown", {})
    earlier_other = count_module.LogRecord("b", when, "tool", "", "q", {}, ["r9"], "h")
    assert count_module.classify(_error(), [earlier_other, later_same], failure) == (
        "other store",
        {"stores_used": ["b"]},
    )
    later_other = count_module.LogRecord("b", failure + timedelta(minutes=1), "tool", "", "q", {}, ["r9"], "h")
    assert count_module.classify_subagent(_error(), [later_other], failure)[0] == "not shown"


def test_captured_errors_repeated_by_a_subagent_are_counted_apart(tmp_path: Path) -> None:
    """Review of #137, finding 2: the captured aggregate covers subagent repeats too."""
    from memkernel.core.models import CAPTURE_ORIGIN_TAG

    a = _settings(tmp_path, "a")
    svc = build_service(a, embedding=MockEmbedding(dimension=384))
    svc.retain("Command `make` failed: `Error: disk full`.", MemoryType.OBSERVATION, tags=[CAPTURE_ORIGIN_TAG])
    del svc
    folder = tmp_path / "transcripts"
    folder.mkdir()
    when = datetime.now(UTC) + timedelta(hours=1)
    Transcript(folder, "s1").tool(when, "Bash", {"command": "ls"}, "src")
    Transcript(folder, "s1", agent="sub").tool(when, "Bash", {"command": "make"}, "Error: disk full", True)
    report = count_module.count(
        [count_module.parse_store(_store_arg(tmp_path, "a"))], count_module.read_sessions(folder, "x")
    )
    assert report["captured_repeats"] == 0 and report["captured_subagent_repeats"] == 1
    assert report["by_outcome_captured_subagent"]["not shown"] == 1
    assert "1 subagent repeat(s) of captured errors" in count_module.render(report)


def test_two_unidentified_sidechains_never_share_a_thread(tmp_path: Path) -> None:
    """Review of #137: one sidechain without an agent id recalls the memory, another fails; neither counts."""
    a = _settings(tmp_path, "a")
    svc = build_service(a, embedding=MockEmbedding(dimension=384))
    m = svc.retain("npm test fails with `Error: Cannot find module 'x'`", MemoryType.FACT)
    del svc
    folder = tmp_path / "transcripts"
    folder.mkdir()
    when = datetime.now(UTC) + timedelta(hours=1)
    stamp = when.isoformat().replace("+00:00", "Z")
    later = (when + timedelta(minutes=1)).isoformat().replace("+00:00", "Z")
    tool = count_module.DEFAULT_RECALL_TOOL
    lines = [
        {
            "sessionId": "s1",
            "timestamp": stamp,
            "isSidechain": True,
            "message": {"content": [{"type": "tool_use", "id": "r", "name": tool, "input": {"query": "module x"}}]},
        },
        {
            "sessionId": "s1",
            "timestamp": later,
            "isSidechain": True,
            "message": {"content": [{"type": "tool_use", "id": "f", "name": "Bash", "input": {"command": "npm test"}}]},
        },
        {
            "sessionId": "s1",
            "timestamp": later,
            "isSidechain": True,
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "f",
                        "is_error": True,
                        "content": "Exit code 1\nError: Cannot find module 'x'",
                    }
                ]
            },
        },
    ]
    (folder / "s1.jsonl").write_text("".join(json.dumps(line) + "\n" for line in lines), encoding="utf-8")
    recall_log.append(a, "tool", [m], query="module x", now=when)
    report = count_module.count(
        [count_module.parse_store(_store_arg(tmp_path, "a"))], count_module.read_sessions(folder, tool)
    )
    assert report["details"] == [] and report["by_outcome_subagent"]["shown"] == 0


# SC-8 on a transcript folder in Claude Code's on-disk shape (memkernel-0-12-capture-core), contributed by DIADE
# after the reproduction on #112 (#136). ``tests/fixtures/transcripts/sc8-claude-code`` holds hand-built lines with
# the fields and line types Claude Code 2.1.x writes: batched results, ``attachment``, ``system``, ``api-request`` and
# ``api-request-blob`` lines (the blob repeats a call's ``tool_use`` and ``tool_result`` parts without a timestamp), a
# hook-blocked call with ``toolDenialKind``, a piped run, subagent and workflow-agent files, and a ``journal.jsonl``.
# ``expected.json`` names each repeat's outcome and why.

SC8_FIXTURE = COUNT.parents[2] / "tests" / "fixtures" / "transcripts" / "sc8-claude-code"
SC8_EXPECTED: dict[str, Any] = json.loads((SC8_FIXTURE / "expected.json").read_text(encoding="utf-8"))


def _parse_time(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def _moved_copy(target: Path, shift: timedelta) -> Path:
    """The fixture folder under ``target``, every line's ``timestamp`` moved by ``shift`` (lines without one kept)."""
    folder = target / "transcripts"
    shutil.copytree(SC8_FIXTURE, folder, ignore=shutil.ignore_patterns("expected.json"))
    for path in folder.rglob("*.jsonl"):
        lines = []
        for line in path.read_text(encoding="utf-8").splitlines():
            entry = json.loads(line)
            if "timestamp" in entry:
                moved = _parse_time(entry["timestamp"]) + shift
                entry["timestamp"] = moved.isoformat(timespec="milliseconds").replace("+00:00", "Z")
            lines.append(json.dumps(entry))
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return folder


def test_the_sc8_fixture_has_the_noise_it_claims() -> None:
    """The fixture keeps its point: blob lines repeat tool parts without a timestamp, one entry batches results."""
    types: set[str] = set()
    blob_parts = batched = 0
    for path in SC8_FIXTURE.rglob("*.jsonl"):
        for line in path.read_text(encoding="utf-8").splitlines():
            entry = json.loads(line)
            types.add(str(entry.get("type")))
            content = (entry.get("message") or {}).get("content")
            parts = [p for p in content if isinstance(p, dict)] if isinstance(content, list) else []
            if entry.get("type") == "api-request-blob":
                assert "timestamp" not in entry
                blob_parts += sum(p.get("type") in {"tool_use", "tool_result"} for p in parts)
            if entry.get("type") == "user" and sum(p.get("type") == "tool_result" for p in parts) > 1:
                batched += 1
    assert {"attachment", "system", "api-request", "api-request-blob", "queue-operation", "last-prompt"} <= types
    assert blob_parts >= 4 and batched >= 1


def test_the_reader_takes_each_sc8_call_once_and_skips_the_journal() -> None:
    reader = ClaudeCodeTranscriptReader()
    files = list(transcript_files(SC8_FIXTURE))
    assert not [p for p in files if p.name == "journal.jsonl"]
    ids: list[str] = []
    for path in files:
        for session in reader.read(path, include_sidechains=True):
            ids.extend(step.tool_use_id for step in session.steps)
    assert len(ids) == len(set(ids))  # the blob copies are not second steps


def test_sc8_outcomes_on_the_claude_code_shaped_folder(tmp_path: Path) -> None:
    settings = _settings(tmp_path, "a")
    svc = build_service(settings, embedding=MockEmbedding(dimension=384))
    refs = {name: svc.retain(text, MemoryType.FACT) for name, text in SC8_EXPECTED["memories"].items()}
    del svc
    shift = (datetime.now(UTC) + timedelta(hours=1)) - _parse_time(SC8_EXPECTED["base"])
    folder = _moved_copy(tmp_path, shift)
    for recall in SC8_EXPECTED["recalls"]:
        ids = [refs[name] for name in recall["memories"]]
        when = _parse_time(recall["at"]) + shift
        if recall["origin"] == "hook":
            recall_log.append(settings, "hook", ids, session_id=recall["session"], block="session-start", now=when)
        else:
            recall_log.append(settings, "tool", ids, query=recall["query"], now=when)

    out = tmp_path / "report.json"
    store = _store_arg(tmp_path, "a")
    assert count_module.main(["--store", store, "--transcripts", str(folder), "--json", str(out)]) == 0
    report = json.loads(out.read_text(encoding="utf-8"))

    found = {(d["session_id"], d["agent_id"]): d for d in report["details"]}
    expected = {(r["session"], r["agent"]): r for r in SC8_EXPECTED["repeats"]}
    assert set(found) == set(expected)
    for key, want in expected.items():
        assert (found[key]["outcome"], found[key]["command"]) == (want["outcome"], want["command"]), want["why"]
        assert found[key]["ref_id"] == refs["left_pad"]
    assert not {session for session, _ in found} & set(SC8_EXPECTED["no_repeat"])
    assert report["stored_errors"] == SC8_EXPECTED["stored_errors"]
    assert report["repeats"] == SC8_EXPECTED["repeats_main"]
    assert report["subagent_repeats"] == SC8_EXPECTED["subagent_repeats"]


def test_repeats_are_grouped_by_the_harness_run_and_agent(tmp_path: Path) -> None:
    """memkernel-0-15-harness-foundations FR-006, A6: per-id outcome counts; several ids on one thread are `several`;
    a thread without ids is not grouped, and a report without any ids has no groups."""
    a = _settings(tmp_path, "a")
    svc = build_service(a, embedding=MockEmbedding(dimension=384))
    svc.retain("agent note: `Error: disk full` on the build host", MemoryType.FACT)
    del svc
    folder = tmp_path / "transcripts"
    folder.mkdir()
    start = datetime.now(UTC) + timedelta(hours=1)
    sessions = {
        "s1": [recall_log.Correlation("run-1", "planner")],
        "s2": [recall_log.Correlation("run-2", "coder")],
        "s3": [recall_log.Correlation("run-1", "coder"), recall_log.Correlation("run-3", "coder")],
        "s4": [recall_log.Correlation()],
    }
    for index, (session_id, ids) in enumerate(sessions.items()):
        when = start + timedelta(minutes=10 * index)
        for offset, correlation in enumerate(ids):
            recall_log.append(
                a,
                "hook",
                [],
                session_id=session_id,
                block="session-start",
                now=when + timedelta(seconds=offset),
                ids=correlation,
            )
        Transcript(folder, session_id).tool(
            when + timedelta(minutes=1), "Bash", {"command": "make"}, "Error: disk full", True
        )
    report = count_module.count(
        [count_module.parse_store(_store_arg(tmp_path, "a"))], count_module.read_sessions(folder, "x")
    )
    assert report["repeats"] == 4
    assert report["by_run"] == {
        "run-1": {"repeats": 1, "by_outcome": {"missed": 1}},
        "run-2": {"repeats": 1, "by_outcome": {"missed": 1}},
        count_module.SEVERAL: {"repeats": 1, "by_outcome": {"missed": 1}},
    }
    assert report["by_agent"] == {
        "coder": {"repeats": 2, "by_outcome": {"missed": 2}},
        "planner": {"repeats": 1, "by_outcome": {"missed": 1}},
    }
    by_session = {d["session_id"]: d for d in report["details"]}
    assert by_session["s1"]["run_id"] == "run-1" and by_session["s1"]["harness_agent_id"] == "planner"
    assert "run_id" not in by_session["s4"] and "harness_agent_id" not in by_session["s4"]
    assert "By run run-1: 1 repeat(s): 1 missed." in count_module.render(report)


def test_a_log_without_harness_ids_reports_no_groups(tmp_path: Path) -> None:
    a = _settings(tmp_path, "a")
    svc = build_service(a, embedding=MockEmbedding(dimension=384))
    svc.retain("agent note: `Error: disk full` on the build host", MemoryType.FACT)
    del svc
    folder = tmp_path / "transcripts"
    folder.mkdir()
    when = datetime.now(UTC) + timedelta(hours=1)
    recall_log.append(a, "hook", [], session_id="s1", block="session-start", now=when)
    Transcript(folder, "s1").tool(when + timedelta(minutes=1), "Bash", {"command": "make"}, "Error: disk full", True)
    report = count_module.count(
        [count_module.parse_store(_store_arg(tmp_path, "a"))], count_module.read_sessions(folder, "x")
    )
    assert report["repeats"] == 1 and "by_run" not in report and "by_agent" not in report
    assert "run_id" not in report["details"][0] and "By run" not in count_module.render(report)

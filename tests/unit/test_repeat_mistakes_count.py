# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""The repeated-mistake count on a fixture with known repeats (memkernel-0-10-recall-log SC-3)."""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from memkernel import recall_log
from memkernel.config import MemKernelSettings
from memkernel.core.models import MemoryType
from memkernel.factory import build_service
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
    """Writes Claude Code transcript lines for one session."""

    def __init__(self, folder: Path, session_id: str) -> None:
        self.path = folder / f"{session_id}.jsonl"
        self.session_id = session_id
        self.calls = 0

    def _write(self, when: datetime, entry_type: str, content: list[dict[str, Any]]) -> None:
        entry = {"type": entry_type, "sessionId": self.session_id, "timestamp": when.isoformat().replace("+00:00", "Z")}
        entry["message"] = {"role": entry_type, "content": content}
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry) + "\n")

    def tool(self, when: datetime, name: str, tool_input: dict[str, Any], result: str) -> None:
        self.calls += 1
        call_id = f"{self.session_id}-{self.calls}"
        self._write(when, "assistant", [{"type": "tool_use", "id": call_id, "name": name, "input": tool_input}])
        self._write(when, "user", [{"type": "tool_result", "tool_use_id": call_id, "content": result}])


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
    s1.tool(at(1), "Bash", {"command": "npm test"}, "Error: Cannot find module 'left-pad'\nRequire stack: ...")
    # S2 missed: the store was used, but the recall that returned the memory came after the failure.
    s2 = Transcript(folder, "s2")
    recall_log.append(a, "hook", [m_plain], session_id="s2", block="session-start", now=at(10))
    s2.tool(at(11), "Bash", {"command": "pytest"}, "FAILED tests/test_db.py::test_migrate  -  AssertionError")
    s2.tool(at(12), tool, {"query": "db migrate failure"}, "[]")
    recall_log.append(a, "tool", [m_missed], query="db migrate failure", now=at(12) + timedelta(seconds=1))
    # S3 other store: the session only used store a; the memory is in store b.
    s3 = Transcript(folder, "s3")
    recall_log.append(a, "hook", [m_plain], session_id="s3", block="session-start", now=at(20))
    s3.tool(at(21), "Bash", {"command": "git status"}, "fatal: not a git repository (or any parent)")
    # S4 unknown: no log records for this session.
    s4 = Transcript(folder, "s4")
    s4.tool(at(30), "Bash", {"command": "python app.py"}, "ModuleNotFoundError: No module named 'yaml'")
    # S5 and S6 make the same recall call at the same moment: the tool record is ambiguous and never guessed.
    s5, s6 = Transcript(folder, "s5"), Transcript(folder, "s6")
    s5.tool(at(40), tool, {"query": "disk"}, "[]")
    s6.tool(at(40), tool, {"query": "disk"}, "[]")
    recall_log.append(a, "tool", [m_two], query="disk", now=at(40))
    s5.tool(at(41), "Bash", {"command": "make test"}, "make: *** Error: disk full")
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
    by_session, possible, unattributed = count_module.attribute(
        records, count_module.read_sessions(folder, count_module.DEFAULT_RECALL_TOOL)
    )
    assert unattributed == 0 and not possible and [r.ref_ids for r in by_session["s1"]] == [["r1"]]


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

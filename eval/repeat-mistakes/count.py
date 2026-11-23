# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""Count repeated mistakes on your own build (memkernel-0-10-recall-log FR-005, #120; the rule from #112).

1. **Stored error:** text a memory quotes in backticks that contains an error word (``Error``, ``Exception``,
   ``Traceback``, ``FAILED``, ``fatal``) and more than one word; each such span is one stored error; matching is
   case-sensitive (D5; memkernel-0-12-capture-core R9).
2. **Repeat:** a session that starts after the memory was stored and whose own ``Bash`` run **failed** with the
   command's own exit status (capture's FR-005 rule, R8) with output containing that text (whitespace collapsed);
   one repeat per memory, session and thread, at the first match (D5). Subagent transcripts are read too, and
   count toward their parent session on a thread of their own (R7, R12, R15).
3. **Outcome** (D6), from the recall logs, before the failure's time: ``shown`` (a recall or hook block of that
   session returned the memory), ``missed`` (the session used the memory's store, and nothing returned it),
   ``other store`` (the session never used that store), ``unknown`` (no log records for that session, or a cut-down
   record of the memory's store before the failure, which cannot show that the memory was not returned).
   A subagent gets no startup context: its repeat is ``shown`` only when its own recall returned the memory, and
   ``not shown`` rather than ``missed`` (R10, R14).

4. **By run and agent** (memkernel-0-15-harness-foundations FR-006, A6): when the log records attributed to a
   repeat's thread carry a harness ``run_id`` or ``agent_id``, the report adds ``by_run`` and ``by_agent``, the same
   outcome counts per id (``several`` when that thread's records name more than one). Without ids it is unchanged.

A hook record names its session; a tool record is paired with the transcript's own recall call (the same full
query, by its hash, within 5 seconds, one to one, nearest first). A record whose candidates lie in more than one
session is never guessed (D2).

Usage:
    poetry run python eval/repeat-mistakes/count.py \\
        --store name=main,chroma=.memkernel/chroma,state=.memkernel/state,project=default \\
        --transcripts ~/.claude/projects/<project folder> [--json report.json]
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "src"))
sys.path.insert(0, str(HERE))

from memkernel import recall_log  # noqa: E402
from memkernel.capture import collapse, is_failure, signatures, stored_text  # noqa: E402
from memkernel.config import MemKernelSettings  # noqa: E402
from memkernel.core.models import CAPTURE_ORIGIN_TAG  # noqa: E402
from memkernel.factory import build_service  # noqa: E402
from memkernel.transcripts.claude_code import ClaudeCodeTranscriptReader, transcript_files  # noqa: E402

PAIR_WINDOW = timedelta(seconds=5)
SHOWN, MISSED, OTHER_STORE, UNKNOWN = "shown", "missed", "other store", "unknown"
NOT_SHOWN = "not shown"  # a subagent's repeat its own recalls did not show (R14); never "missed"
OUTCOMES = (SHOWN, MISSED, OTHER_STORE, UNKNOWN)
SUBAGENT_OUTCOMES = (SHOWN, NOT_SHOWN, OTHER_STORE, UNKNOWN)
MAIN_THREAD = ""
SEVERAL = "several"  # a thread whose log records name more than one run or agent id
DEFAULT_RECALL_TOOL = "mcp__memkernel__recall"
LIMITS = (
    "exact text only: a reworded or differently quoted error is not matched",
    "only a Bash run that failed with its own exit status counts; errors seen through other tools are not",
    "a command piped into a filter without pipefail (such as 2>&1 | tail -20) exits with the filter's status: its "
    "failure is not counted",
    "an error printed by a command that exits 0, and a note or listing read through Bash, are not failures",
    "a lesson written in prose, with no quoted error, has no stored error; nor does a single-word quote such as "
    "`ValueError`, while a multi-word code fragment such as `except Exception:` still counts",
    "a session whose recalls were not logged (log off, or ambiguous pairing) is unknown",
    "recalls made through the Python library, not the MCP tool or a hook, are not logged",
    "whether a memory was flagged for review when a recall ran is not known: a recall that hid flagged memories "
    "may have hidden it",
    "a miss is reported as unknown when a record of that store with cut-down ref_ids came before the failure, or an "
    "ambiguous record that may belong to the session could have returned the memory",
    "only Claude Code transcripts are read",
)


@dataclass
class Store:
    name: str
    settings: MemKernelSettings


@dataclass
class StoredError:
    store: str
    ref_id: str
    type: str
    tier: str
    checkpoint: bool
    session_id: str
    time: datetime
    signature: str
    captured: bool = False  # from a captured record (tagged origin:capture), reported apart (FR-011)


@dataclass
class LogRecord:
    store: str
    time: datetime
    origin: str
    session_id: str
    query: str
    filters: dict[str, Any]
    ref_ids: list[str]
    query_sha256: str = ""
    truncated: bool = False  # ref_ids were cut: not proof that a memory was not returned
    run_id: str = ""  # the harness's ids (memkernel-0-15-harness-foundations FR-002), empty in older logs
    agent_id: str = ""


@dataclass
class Repeat:
    store: str
    ref_id: str
    session_id: str
    failure_time: str
    signature: str
    outcome: str
    evidence: dict[str, Any] = field(default_factory=dict)
    command: str = ""  # the failing run's command, redacted and cut (R8)
    agent_id: str = MAIN_THREAD  # empty on the main thread; a subagent's repeat is reported apart (R10)
    captured: bool = False  # the memory is a captured record (FR-011)
    run_id: str = ""  # the harness's run and agent ids from the thread's log records (A6); not Claude Code's agent_id
    harness_agent_id: str = ""


@dataclass
class Output:
    """A failed run's output (R8) on one thread."""

    time: datetime
    text: str
    command: str
    thread: str = MAIN_THREAD


@dataclass
class RecallCall:
    time: datetime
    query: str
    thread: str = MAIN_THREAD


@dataclass
class Session:
    session_id: str
    start: datetime
    end: datetime
    outputs: list[Output] = field(default_factory=list)
    recalls: list[RecallCall] = field(default_factory=list)


def read_sessions(folder: Path, recall_tool: str) -> list[Session]:
    """Every session under ``folder``, subagent files included and merged into their parent session (R7, R15),
    oldest first: its window, its failed runs and its recall calls, each on its thread (R12)."""
    reader = ClaudeCodeTranscriptReader()
    sessions: dict[str, Session] = {}
    for path in transcript_files(folder):
        try:
            found = reader.read(path, include_sidechains=True)
        except OSError:
            continue
        for read in found:
            session = sessions.setdefault(read.session_id, Session(read.session_id, read.start, read.end))
            session.start, session.end = min(session.start, read.start), max(session.end, read.end)
            for step in read.steps:
                if is_failure(step):
                    session.outputs.append(Output(step.time, step.result, step.command, step.agent_id))
                elif step.tool == recall_tool:
                    session.recalls.append(RecallCall(step.time, step.query, step.agent_id))
    for session in sessions.values():
        session.outputs.sort(key=lambda o: o.time)
        session.recalls.sort(key=lambda c: c.time)
    return sorted(sessions.values(), key=lambda s: s.start)


class _NoEmbedding:
    """Reading a store lists records; nothing is embedded, so the model is never loaded."""

    def __init__(self, dimension: int) -> None:
        self.dimension = dimension

    def embed(self, texts: list[str]) -> list[list[float]]:
        raise RuntimeError("the count reads the store only")


def parse_store(spec: str) -> Store:
    """``name=…,chroma=…,state=…,project=…``; name defaults to the project id."""
    parts = dict(item.split("=", 1) for item in spec.split(",") if "=" in item)
    missing = {"chroma", "state", "project"} - parts.keys()
    if missing:
        raise SystemExit(f"--store {spec!r}: missing {', '.join(sorted(missing))}")
    if not Path(parts["chroma"]).is_dir():
        raise SystemExit(f"--store {spec!r}: no store at {parts['chroma']}")  # reading must not create one
    settings = MemKernelSettings(
        chroma_persist_path=parts["chroma"], state_dir=parts["state"], project_id=parts["project"]
    )
    return Store(parts.get("name", parts["project"]), settings)


def stored_errors(store: Store) -> list[StoredError]:
    svc = build_service(store.settings, embedding=_NoEmbedding(store.settings.embedding_dimension))
    found = []
    for memory in svc.list_memories(include_superseded=True):
        if memory.parent_ref is not None:
            continue  # a code chunk: its owner carries the text
        for signature in signatures(memory.content):
            found.append(
                StoredError(
                    store.name,
                    memory.ref_id,
                    memory.type.value,
                    memory.tier.value,
                    memory.checkpoint,
                    memory.session_id,
                    memory.timestamp,
                    signature,
                    CAPTURE_ORIGIN_TAG in memory.tags,
                )
            )
    return found


def _parse(store: str, raw: Any) -> LogRecord | None:
    """One log line as a record, or None when any field has the wrong type (a malformed line is never guessed)."""
    if not isinstance(raw, dict):
        return None
    try:
        when = datetime.fromisoformat(raw["time"])
    except (KeyError, TypeError, ValueError):
        return None
    fields = {
        "origin": raw.get("origin"),
        "session_id": raw.get("session_id", ""),
        "query": raw.get("query", ""),
        "query_sha256": raw.get("query_sha256", ""),
        "run_id": raw.get("run_id", ""),
        "agent_id": raw.get("agent_id", ""),
    }
    filters, ref_ids = raw.get("filters", {}), raw.get("ref_ids", [])
    truncated, ids_cut = raw.get("truncated", False), raw.get("ref_ids_truncated", False)
    if (
        when.tzinfo is None
        or fields["origin"] not in (recall_log.ORIGIN_TOOL, recall_log.ORIGIN_HOOK)
        or not all(isinstance(value, str) for value in fields.values())
        or not isinstance(filters, dict)
        or not isinstance(ref_ids, list)
        or not all(isinstance(ref, str) for ref in ref_ids)
        or not isinstance(truncated, bool)
        or not isinstance(ids_cut, bool)
    ):
        return None
    return LogRecord(
        store,
        when,
        fields["origin"],
        fields["session_id"],
        fields["query"],
        filters,
        ref_ids,
        fields["query_sha256"],
        ids_cut,  # a record that lost only query text still lists every id it returned
        fields["run_id"],
        fields["agent_id"],
    )


def read_log(store: Store) -> tuple[list[LogRecord], int]:
    """Every record of the store's recall log, rotated files included, oldest first; and how many lines were skipped
    as malformed."""
    current = (
        Path(store.settings.state_dir)
        / recall_log.RECALL_LOG_DIR
        / store.settings.project_id
        / recall_log.RECALL_LOG_FILE
    )
    records: list[LogRecord] = []
    malformed = 0
    for path in [current, *current.parent.glob(f"{current.name}.[0-9]*")]:
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                record = _parse(store.name, json.loads(line))
            except json.JSONDecodeError:
                record = None
            if record is None:
                malformed += 1
            else:
                records.append(record)
    return sorted(records, key=lambda r: r.time), malformed


Thread = tuple[str, str]  # (session id, agent id); the agent id is empty on the main thread


def attribute(
    records: list[LogRecord], sessions: list[Session]
) -> tuple[dict[Thread, list[LogRecord]], dict[Thread, list[LogRecord]], int]:
    """Records per thread (D2, R12): a hook record belongs to its session's main thread, a tool record to the thread
    whose recall call it pairs with; per thread, the ambiguous tool records that may be its own; and how many tool
    records were not attributed (ambiguous or unpaired)."""
    by_thread: dict[Thread, list[LogRecord]] = {}
    possible: dict[Thread, list[LogRecord]] = {}
    pairs: list[tuple[timedelta, int, Thread, int]] = []
    candidates: dict[int, set[Thread]] = {}
    tool_records: list[LogRecord] = []
    for record in records:
        if record.origin == recall_log.ORIGIN_HOOK:
            if record.session_id:
                by_thread.setdefault((record.session_id, MAIN_THREAD), []).append(record)
            continue
        index = len(tool_records)
        tool_records.append(record)
        for session in sessions:
            for call_index, call in enumerate(session.recalls):
                gap = abs(call.time - record.time)
                if gap <= PAIR_WINDOW and recall_log.query_hash(call.query) == record.query_sha256:
                    thread = (session.session_id, call.thread)
                    pairs.append((gap, index, thread, call_index))
                    candidates.setdefault(index, set()).add(thread)
    used_records: set[int] = set()
    used_calls: set[tuple[Thread, int]] = set()
    for _gap, index, thread, call_index in sorted(pairs, key=lambda p: (p[0], p[1])):
        if index in used_records or (thread, call_index) in used_calls:
            continue
        if len(candidates[index]) > 1:
            continue  # candidates on more than one thread: never guessed, kept below as possible
        used_records.add(index)
        used_calls.add((thread, call_index))
        by_thread.setdefault(thread, []).append(tool_records[index])
    for index, threads in candidates.items():
        if len(threads) > 1:
            for thread in threads:
                possible.setdefault(thread, []).append(tool_records[index])
    unattributed = len(tool_records) - len(used_records)
    return by_thread, possible, unattributed


def _excluded(record: LogRecord, error: StoredError) -> bool:
    """True when the MCP recall's filters could not have returned the memory.

    ``include_needs_review`` is not judged: whether the memory was flagged when the recall ran is not known."""
    filters = record.filters
    if filters.get("type") and filters["type"] != error.type:
        return True
    if filters.get("tier") and filters["tier"] != error.tier:
        return True
    if filters.get("session_id_filter") and filters["session_id_filter"] != error.session_id:
        return True
    return bool(filters.get("checkpoint_only")) and not error.checkpoint


def classify(
    error: StoredError, records: list[LogRecord], failure: datetime, possible: list[LogRecord] | None = None
) -> tuple[str, dict[str, Any]]:
    before = [r for r in records if r.time < failure]  # only what came before the failure is evidence
    if not before:
        return UNKNOWN, {}
    if any(r.store == error.store and error.ref_id in r.ref_ids for r in before):
        return SHOWN, {}
    if any(
        r.store == error.store and r.time < failure and (error.ref_id in r.ref_ids or r.truncated)
        for r in possible or []
    ):
        return UNKNOWN, {"ambiguous_record_may_have_shown": True}
    if any(r.store == error.store and r.truncated for r in before):
        return UNKNOWN, {"truncated_record_before_failure": True}
    if error.store in {r.store for r in before}:
        tool = [r for r in before if r.store == error.store and r.origin == recall_log.ORIGIN_TOOL]
        hook = [r for r in before if r.store == error.store and r.origin == recall_log.ORIGIN_HOOK]
        return MISSED, {
            "tool_recalls_before_failure": len(tool),
            "hook_blocks_before_failure": len(hook),
            "all_tool_recalls_filtered_out": bool(tool) and all(_excluded(r, error) for r in tool),
        }
    return OTHER_STORE, {"stores_used": sorted({r.store for r in before})}


def classify_subagent(
    error: StoredError, records: list[LogRecord], failure: datetime, possible: list[LogRecord] | None = None
) -> tuple[str, dict[str, Any]]:
    """A subagent's repeat (R10, R14): ``shown`` only when its own recall returned the memory before the failure;
    ``unknown`` and ``other store`` as on the main thread; otherwise ``not shown``, never ``missed``."""
    before = [r for r in records if r.time < failure]
    if any(r.store == error.store and error.ref_id in r.ref_ids for r in before):
        return SHOWN, {}
    if any(
        r.store == error.store and r.time < failure and (error.ref_id in r.ref_ids or r.truncated)
        for r in possible or []
    ):
        return UNKNOWN, {"ambiguous_record_may_have_shown": True}
    if any(r.store == error.store and r.truncated for r in before):
        return UNKNOWN, {"truncated_record_before_failure": True}
    if before and error.store not in {r.store for r in before}:
        return OTHER_STORE, {"stores_used": sorted({r.store for r in before})}
    return NOT_SHOWN, {"tool_recalls_before_failure": sum(r.store == error.store for r in before)}


def _one_id(values: list[str]) -> str:
    """The id a thread's records name: the one non-empty value, SEVERAL for more than one, empty for none."""
    named = {value for value in values if value}
    return SEVERAL if len(named) > 1 else next(iter(named), "")


def _grouped(repeats: list[Repeat], key: str) -> dict[str, dict[str, Any]]:
    """Repeat and outcome counts per harness id (A6); repeats without one are left out."""
    groups: dict[str, dict[str, Any]] = {}
    for repeat in repeats:
        name = getattr(repeat, key)
        if not name:
            continue
        group = groups.setdefault(name, {"repeats": 0, "by_outcome": {}})
        group["repeats"] += 1
        group["by_outcome"][repeat.outcome] = group["by_outcome"].get(repeat.outcome, 0) + 1
    return dict(sorted(groups.items()))


def _detail(repeat: Repeat) -> dict[str, Any]:
    """A repeat for the report; the harness ids only when set, so a log without them reports as before (A6)."""
    detail = asdict(repeat)
    for key in ("run_id", "harness_agent_id"):
        if not detail[key]:
            del detail[key]
    return detail


def count(stores: list[Store], sessions: list[Session]) -> dict[str, Any]:
    errors = [e for store in stores for e in stored_errors(store)]
    logs = [read_log(store) for store in stores]
    records = [r for log, _ in logs for r in log]
    by_thread, possible, unattributed = attribute(records, sessions)
    repeats: list[Repeat] = []
    shown_without_repeat: set[str] = set()
    memories: dict[tuple[str, str], list[StoredError]] = {}
    for error in errors:
        memories.setdefault((error.store, error.ref_id), []).append(error)
    for (store_name, ref_id), group in memories.items():
        stored_at = group[0].time
        for session in sessions:
            if session.start <= stored_at:
                continue
            hits: dict[str, tuple[Output, StoredError]] = {}
            for out in session.outputs:
                if out.thread in hits:
                    continue
                matched = next((e for e in group if e.signature in collapse(out.text)), None)
                if matched is not None:
                    hits[out.thread] = (out, matched)
            if not hits:
                session_records = [r for (sid, _), rs in by_thread.items() if sid == session.session_id for r in rs]
                if any(r.store == store_name and ref_id in r.ref_ids for r in session_records):
                    shown_without_repeat.add(session.session_id)
                continue
            for thread, (out, error) in hits.items():
                key = (session.session_id, thread)
                judge = classify if thread == MAIN_THREAD else classify_subagent
                thread_records = by_thread.get(key, [])
                outcome, evidence = judge(error, thread_records, out.time, possible.get(key))
                repeats.append(
                    Repeat(
                        store_name,
                        ref_id,
                        session.session_id,
                        out.time.isoformat(),
                        error.signature,
                        outcome,
                        evidence,
                        stored_text(out.command),
                        thread,
                        error.captured,
                        _one_id([r.run_id for r in thread_records]),
                        _one_id([r.agent_id for r in thread_records]),
                    )
                )
    main = [r for r in repeats if r.agent_id == MAIN_THREAD]
    subagent = [r for r in repeats if r.agent_id != MAIN_THREAD]
    report: dict[str, Any] = {
        "stored_errors": len(errors),
        "captured_errors": sum(e.captured for e in errors),
        "memories_with_errors": len(memories),
        "sessions": len(sessions),
        "repeats": len(main),
        "by_outcome": {o: sum(r.outcome == o for r in main) for o in OUTCOMES},
        "captured_repeats": sum(r.captured for r in main),
        "by_outcome_captured": {o: sum(r.outcome == o for r in main if r.captured) for o in OUTCOMES},
        "captured_subagent_repeats": sum(r.captured for r in subagent),
        "by_outcome_captured_subagent": {
            o: sum(r.outcome == o for r in subagent if r.captured) for o in SUBAGENT_OUTCOMES
        },
        "subagent_repeats": len(subagent),
        "by_outcome_subagent": {o: sum(r.outcome == o for r in subagent) for o in SUBAGENT_OUTCOMES},
        "shown_without_repeat": len(shown_without_repeat),
        "unattributed_tool_records": unattributed,
        "malformed_log_records": sum(bad for _, bad in logs),
        "details": [_detail(r) for r in repeats],
        "limits": list(LIMITS),
    }
    for name, key in (("by_run", "run_id"), ("by_agent", "harness_agent_id")):
        groups = _grouped(repeats, key)
        if groups:
            report[name] = groups
    return report


def render(report: dict[str, Any]) -> str:
    lines = [
        f"{report['stored_errors']} stored error(s) in {report['memories_with_errors']} memory record(s); "
        f"{report['sessions']} session(s) read.",
        f"{report['repeats']} repeat(s): "
        + ", ".join(f"{report['by_outcome'][o]} {o}" for o in OUTCOMES)
        + f". {report['shown_without_repeat']} later session(s) were shown a memory and did not repeat its error.",
    ]
    if report["captured_errors"]:
        lines.append(
            f"{report['captured_errors']} of the stored errors are from captured records; "
            f"{report['captured_repeats']} of the repeats above came back after capture: "
            + ", ".join(f"{report['by_outcome_captured'][o]} {o}" for o in OUTCOMES)
            + "."
            + (
                f" {report['captured_subagent_repeats']} subagent repeat(s) of captured errors: "
                + ", ".join(f"{report['by_outcome_captured_subagent'][o]} {o}" for o in SUBAGENT_OUTCOMES)
                + "."
                if report["captured_subagent_repeats"]
                else ""
            )
        )
    if report["subagent_repeats"]:
        lines.append(
            f"{report['subagent_repeats']} subagent repeat(s), reported apart (a subagent gets no startup context): "
            + ", ".join(f"{report['by_outcome_subagent'][o]} {o}" for o in SUBAGENT_OUTCOMES)
            + "."
        )
    if report["malformed_log_records"]:
        lines.append(f"{report['malformed_log_records']} malformed recall-log line(s) were skipped.")
    if report["unattributed_tool_records"]:
        lines.append(f"{report['unattributed_tool_records']} tool record(s) could not be paired with a session.")
    for name, label in (("by_run", "run"), ("by_agent", "agent")):
        for harness_id, group in report.get(name, {}).items():
            outcomes = ", ".join(f"{n} {o}" for o, n in sorted(group["by_outcome"].items()))
            lines.append(f"By {label} {harness_id}: {group['repeats']} repeat(s): {outcomes}.")
    for r in report["details"]:
        thread = (f" (subagent {r['agent_id']})" if r["agent_id"] else "") + (" (captured)" if r["captured"] else "")
        lines.append(
            f"- [{r['outcome']}] {r['store']}:{r['ref_id']} session {r['session_id']}{thread} at {r['failure_time']}"
        )
        lines.append(f"    `{r['signature']}` from `{r['command']}`" + (f" {r['evidence']}" if r["evidence"] else ""))
    lines.append("Limits: " + "; ".join(report["limits"]) + ".")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--store", action="append", required=True, help="name=…,chroma=…,state=…,project=…")
    parser.add_argument("--transcripts", required=True, type=Path, help="a Claude Code project transcript folder")
    parser.add_argument("--recall-tool", default=DEFAULT_RECALL_TOOL, help="the MCP tool name of memkernel's recall")
    parser.add_argument("--json", type=Path, help="also write the report as JSON")
    args = parser.parse_args(argv)
    report = count([parse_store(s) for s in args.store], read_sessions(args.transcripts, args.recall_tool))
    print(render(report))
    if args.json:
        args.json.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

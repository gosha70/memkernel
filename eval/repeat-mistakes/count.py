# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""Count repeated mistakes on your own build (memkernel-0-10-recall-log FR-005, #120; the rule from #112).

1. **Stored error:** text a memory quotes in backticks that contains an error word (``Error``, ``Exception``,
   ``Traceback``, ``FAILED``, ``fatal``); each such span is one stored error; matching is case-sensitive (D5).
2. **Repeat:** a session that starts after the memory was stored and whose own ``Bash`` output contains that text
   (whitespace collapsed); one repeat per memory and session, at the first match (D5).
3. **Outcome** (D6), from the recall logs, before the failure's time: ``shown`` (a recall or hook block of that
   session returned the memory), ``missed`` (the session used the memory's store, and nothing returned it),
   ``other store`` (the session never used that store), ``unknown`` (no log records for that session).

A hook record names its session; a tool record is paired with the transcript's own recall call (same query, within
5 seconds, one to one, nearest first). A record whose candidates lie in more than one session is never guessed (D2).

Usage:
    poetry run python eval/repeat-mistakes/count.py \\
        --store name=main,chroma=.memkernel/chroma,state=.memkernel/state,project=default \\
        --transcripts ~/.claude/projects/<project folder> [--json report.json]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "src"))
sys.path.insert(0, str(HERE))

from transcripts import Session, read_sessions  # noqa: E402

from memkernel import recall_log  # noqa: E402
from memkernel.config import MemKernelSettings  # noqa: E402
from memkernel.factory import build_service  # noqa: E402

ERROR_WORDS = ("Error", "Exception", "Traceback", "FAILED", "fatal")
PAIR_WINDOW = timedelta(seconds=5)
SHOWN, MISSED, OTHER_STORE, UNKNOWN = "shown", "missed", "other store", "unknown"
OUTCOMES = (SHOWN, MISSED, OTHER_STORE, UNKNOWN)
DEFAULT_RECALL_TOOL = "mcp__memkernel__recall"
LIMITS = (
    "exact text only: a reworded or differently quoted error is not matched",
    "only Bash output counts as a failure; errors seen through other tools are not",
    "a session whose recalls were not logged (log off, or ambiguous pairing) is unknown",
    "recalls made through the Python library, not the MCP tool or a hook, are not logged",
    "only Claude Code transcripts are read",
)


def collapse(text: str) -> str:
    return " ".join(text.split())


def signatures(content: str) -> list[str]:
    """The stored errors in a memory's content (D5), in order, without duplicates."""
    spans = [collapse(s) for s in re.findall(r"`([^`\n]+)`", content)]
    return list(dict.fromkeys(s for s in spans if any(word in s for word in ERROR_WORDS)))


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
    needs_review: bool  # as the store holds it now: a flag set or cleared since the failure is not known
    time: datetime
    signature: str


@dataclass
class LogRecord:
    store: str
    time: datetime
    origin: str
    session_id: str
    query: str
    filters: dict[str, Any]
    ref_ids: list[str]


@dataclass
class Repeat:
    store: str
    ref_id: str
    session_id: str
    failure_time: str
    signature: str
    outcome: str
    evidence: dict[str, Any] = field(default_factory=dict)


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
                    memory.needs_review,
                    memory.timestamp,
                    signature,
                )
            )
    return found


def read_log(store: Store) -> list[LogRecord]:
    """Every record of the store's recall log, rotated files included, oldest first."""
    current = (
        Path(store.settings.state_dir)
        / recall_log.RECALL_LOG_DIR
        / store.settings.project_id
        / recall_log.RECALL_LOG_FILE
    )
    records = []
    for path in [current, *current.parent.glob(f"{current.name}.[0-9]*")]:
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                raw = json.loads(line)
                records.append(
                    LogRecord(
                        store.name,
                        datetime.fromisoformat(raw["time"]),
                        raw["origin"],
                        raw.get("session_id", ""),
                        raw.get("query", ""),
                        raw.get("filters", {}),
                        list(raw.get("ref_ids", [])),
                    )
                )
            except (ValueError, KeyError, TypeError):
                continue
    return sorted(records, key=lambda r: r.time)


def attribute(records: list[LogRecord], sessions: list[Session]) -> tuple[dict[str, list[LogRecord]], int]:
    """Records per session (D2), and how many tool records stayed ambiguous or unpaired."""
    by_session: dict[str, list[LogRecord]] = {}
    pairs: list[tuple[timedelta, int, str, int]] = []
    candidate_sessions: dict[int, set[str]] = {}
    tool_records: list[LogRecord] = []
    for record in records:
        if record.origin == recall_log.ORIGIN_HOOK:
            if record.session_id:
                by_session.setdefault(record.session_id, []).append(record)
            continue
        index = len(tool_records)
        tool_records.append(record)
        for session in sessions:
            for call_index, call in enumerate(session.recalls):
                gap = abs(call.time - record.time)
                if call.query[: recall_log.QUERY_MAX_CHARS] == record.query and gap <= PAIR_WINDOW:
                    pairs.append((gap, index, session.session_id, call_index))
                    candidate_sessions.setdefault(index, set()).add(session.session_id)
    used_records: set[int] = set()
    used_calls: set[tuple[str, int]] = set()
    for _gap, index, session_id, call_index in sorted(pairs, key=lambda p: (p[0], p[1])):
        if index in used_records or (session_id, call_index) in used_calls:
            continue
        if len(candidate_sessions[index]) > 1:
            continue  # candidates in more than one session: never guessed
        used_records.add(index)
        used_calls.add((session_id, call_index))
        by_session.setdefault(session_id, []).append(tool_records[index])
    unattributed = len(tool_records) - len(used_records)
    return by_session, unattributed


def _excluded(record: LogRecord, error: StoredError) -> bool:
    """True when the MCP recall's filters could not have returned the memory (every filter the log records)."""
    filters = record.filters
    if filters.get("type") and filters["type"] != error.type:
        return True
    if filters.get("tier") and filters["tier"] != error.tier:
        return True
    if filters.get("session_id_filter") and filters["session_id_filter"] != error.session_id:
        return True
    if error.needs_review and not filters.get("include_needs_review"):
        return True
    return bool(filters.get("checkpoint_only")) and not error.checkpoint


def classify(error: StoredError, records: list[LogRecord], failure: datetime) -> tuple[str, dict[str, Any]]:
    if not records:
        return UNKNOWN, {}
    before = [r for r in records if r.time < failure]
    if any(r.store == error.store and error.ref_id in r.ref_ids for r in before):
        return SHOWN, {}
    if error.store in {r.store for r in records}:
        tool = [r for r in before if r.store == error.store and r.origin == recall_log.ORIGIN_TOOL]
        hook = [r for r in before if r.store == error.store and r.origin == recall_log.ORIGIN_HOOK]
        return MISSED, {
            "tool_recalls_before_failure": len(tool),
            "hook_blocks_before_failure": len(hook),
            "all_tool_recalls_filtered_out": bool(tool) and all(_excluded(r, error) for r in tool),
        }
    return OTHER_STORE, {"stores_used": sorted({r.store for r in records})}


def count(stores: list[Store], sessions: list[Session]) -> dict[str, Any]:
    errors = [e for store in stores for e in stored_errors(store)]
    records = [r for store in stores for r in read_log(store)]
    by_session, unattributed = attribute(records, sessions)
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
            hit = next(
                ((out.time, e) for out in session.outputs for e in group if e.signature in collapse(out.text)),
                None,
            )
            session_records = by_session.get(session.session_id, [])
            if hit is None:
                if any(r.store == store_name and ref_id in r.ref_ids for r in session_records):
                    shown_without_repeat.add(session.session_id)
                continue
            failure, error = hit
            outcome, evidence = classify(error, session_records, failure)
            repeats.append(
                Repeat(store_name, ref_id, session.session_id, failure.isoformat(), error.signature, outcome, evidence)
            )
    return {
        "stored_errors": len(errors),
        "memories_with_errors": len(memories),
        "sessions": len(sessions),
        "repeats": len(repeats),
        "by_outcome": {o: sum(r.outcome == o for r in repeats) for o in OUTCOMES},
        "shown_without_repeat": len(shown_without_repeat),
        "unattributed_tool_records": unattributed,
        "details": [asdict(r) for r in repeats],
        "limits": list(LIMITS),
    }


def render(report: dict[str, Any]) -> str:
    lines = [
        f"{report['stored_errors']} stored error(s) in {report['memories_with_errors']} memory record(s); "
        f"{report['sessions']} session(s) read.",
        f"{report['repeats']} repeat(s): "
        + ", ".join(f"{report['by_outcome'][o]} {o}" for o in OUTCOMES)
        + f". {report['shown_without_repeat']} later session(s) were shown a memory and did not repeat its error.",
    ]
    if report["unattributed_tool_records"]:
        lines.append(f"{report['unattributed_tool_records']} tool record(s) could not be paired with a session.")
    for r in report["details"]:
        lines.append(f"- [{r['outcome']}] {r['store']}:{r['ref_id']} session {r['session_id']} at {r['failure_time']}")
        lines.append(f"    `{r['signature']}`" + (f" {r['evidence']}" if r["evidence"] else ""))
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

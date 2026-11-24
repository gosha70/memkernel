# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""Compare the context a run received with the store now (memkernel-0-15-harness-foundations H3: FR-004, SC-2).

Reads a run's receipts from the recall log (MCP recalls and hook blocks whose ``run_id`` is the run's; H1) and gives
each memory the run received the statuses that apply against the store now (amendment H3, C1–C9):

- ``missing``: no record, or expired. It stands alone.
- ``superseded`` (with what replaced it) or ``withdrawn`` (with the reason): read from the store.
- ``changed``: another ``content_hash`` under the same hashing scheme, for a record that still exists (a deleted
  chunk is judged through its file record). ``rehashed``: the receipt's hash was made with another scheme than this
  memkernel's, so it is not compared (C2); for code, the source check then only notices a file that is gone.
- ``flagged``: needs review now, and ``live`` in its receipt (the run did not see a flag).
- ``source changed`` (decisions and code only, as revalidation: another record's ``source`` is a label, such as
  ``capture``): the memory's ``source`` file under the project root no longer hashes to the receipt's
  ``source_hash`` (a decision) or ``content_hash`` (code), through memkernel's own ``compute_content_hash``; a file
  that is gone counts too. It says nothing about whether the memory is wrong, or about other files its text cites.
- ``unknown``: no receipt in the run has the memory's hash (every record that returned it was cut down). It combines
  only with ``superseded`` and ``withdrawn``.
- ``unchanged``: nothing else applies.

Each memory is judged by the last receipt in the run that has its hash (C1). A code chunk is judged by the file record
it belongs to: its ``parent_ref``, the id's prefix (``<owner>-chunk-<n>``) once the chunk record is gone, or, for a
chunk from before 0.4, the code record whose ``chunk_refs`` lists it (as revalidation recognises it). Source checks
need ``root=``, the project the sources resolve under; without it they are skipped and each memory with a source
says so. Unreadable log files are skipped and counted. The report holds ids, hashes, sources and statuses, never
memory content; it reads every scope, and opens the store without creating anything. Exit codes: 0 report printed,
1 no record carries the run id, 2 usage error, or a store it cannot open or read (no collection for the project
included).

Usage:
    poetry run python eval/context-diff/diff.py \\
        --store name=main,chroma=.memkernel/chroma,state=.memkernel/state,project=default[,root=/path/to/project] \\
        --run <run_id> [--json report.json]
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "src"))

import chromadb  # noqa: E402
from chromadb.errors import ChromaError  # noqa: E402

from memkernel import recall_log  # noqa: E402
from memkernel.config import MemKernelSettings  # noqa: E402
from memkernel.core.models import MemoryType  # noqa: E402
from memkernel.memory.dedup import CONTENT_HASH_SCHEME, compute_content_hash  # noqa: E402
from memkernel.memory.lifecycle import memory_is_expired  # noqa: E402
from memkernel.storage.chroma import ChromaVectorStore  # noqa: E402

if TYPE_CHECKING:
    from memkernel.core.models import Memory
    from memkernel.core.ports import VectorStorePort

MISSING = "missing"
SUPERSEDED = "superseded"
WITHDRAWN = "withdrawn"
CHANGED = "changed"
REHASHED = "rehashed"
FLAGGED = "flagged"
SOURCE_CHANGED = "source changed"
UNKNOWN = "unknown"
UNCHANGED = "unchanged"
STATUSES = (MISSING, SUPERSEDED, WITHDRAWN, CHANGED, REHASHED, FLAGGED, SOURCE_CHANGED, UNKNOWN, UNCHANGED)
CHUNK_INFIX = "-chunk-"  # a code chunk's id: <owner ref_id>-chunk-<n>
NOTE_NO_ROOT = "no source check (no root given)"
NOTE_OUTSIDE_ROOT = "no source check (outside the project root)"
NOTE_UNREADABLE = "no source check (the file cannot be read as text)"
EXIT_REPORT, EXIT_NO_RECORDS, EXIT_USAGE = 0, 1, 2
SOURCE_CHECKED_TYPES = (MemoryType.DECISION, MemoryType.CODE)  # as revalidation: other records' sources are labels
STORE_ERRORS = (ChromaError, OSError, ValueError, RuntimeError)


class StoreUnavailableError(Exception):
    """The store cannot be opened or read (exit 2): no collection for the project, or chromadb failed."""


@dataclass
class Judged:
    """One memory the run received, with its statuses (C3) and what explains them."""

    ref_id: str
    statuses: list[str]
    source: str = ""
    scope: str = ""
    superseded_by: str = ""
    withdrawn_reason: str = ""
    owner: str = ""  # a code chunk's file record
    notes: list[str] = field(default_factory=list)


def parse_store(spec: str) -> tuple[MemKernelSettings, Path | None]:
    """``name=…,chroma=…,state=…,project=…[,root=…]``: the count's store format, plus ``root``, the project that
    sources resolve under (None when not given: no source checks). A bad spec or a missing store exits 2 (C5)."""
    parts = dict(item.split("=", 1) for item in spec.split(",") if "=" in item)
    missing = {"chroma", "state", "project"} - parts.keys()
    if missing:
        print(f"--store {spec!r}: missing {', '.join(sorted(missing))}", file=sys.stderr)
        raise SystemExit(EXIT_USAGE)
    if not Path(parts["chroma"]).is_dir():
        print(f"--store {spec!r}: no store at {parts['chroma']}", file=sys.stderr)  # reading must not create one
        raise SystemExit(EXIT_USAGE)
    root = Path(parts["root"]).resolve() if parts.get("root") else None
    settings = MemKernelSettings(
        chroma_persist_path=parts["chroma"], state_dir=parts["state"], project_id=parts["project"]
    )
    return settings, root


def open_store(settings: MemKernelSettings) -> VectorStorePort:
    """The project's store, opened without creating a collection; ``StoreUnavailableError`` when it has none or chromadb
    fails (the adapter itself would create a missing collection, so its existence is checked first)."""
    name = f"{settings.chroma_collection_prefix}_{settings.project_id}"
    try:
        client = chromadb.PersistentClient(path=settings.chroma_persist_path)
        client.get_collection(name)  # raises NotFoundError for a missing collection; creates nothing
        return ChromaVectorStore(settings, client=client)
    except STORE_ERRORS as exc:
        where = settings.chroma_persist_path
        raise StoreUnavailableError(f"no readable collection {name!r} at {where} ({exc})") from exc


def run_records(settings: MemKernelSettings, run_id: str) -> tuple[list[dict[str, Any]], int]:
    """Every recall-log record of the store whose ``run_id`` is ``run_id``, rotated files included, oldest first, and
    how many log files could not be read (one being rotated, or damaged) and were skipped. Lines that are not JSON
    objects are skipped."""
    current = Path(settings.state_dir) / recall_log.RECALL_LOG_DIR / settings.project_id / recall_log.RECALL_LOG_FILE
    records: list[dict[str, Any]] = []
    unreadable = 0
    for path in [current, *current.parent.glob(f"{current.name}.[0-9]*")]:
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            unreadable += 1
            continue
        for line in text.splitlines():
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict) and record.get("run_id") == run_id:
                records.append(record)
    return sorted(records, key=lambda r: str(r.get("time", ""))), unreadable


def received(records: list[dict[str, Any]]) -> tuple[list[str], dict[str, dict[str, Any]]]:
    """The memories the run received, in first-seen order, and for each the last receipt entry with its hash (C1)."""
    order: list[str] = []
    entries: dict[str, dict[str, Any]] = {}
    for record in records:
        details = {
            e["ref_id"]: e
            for e in record.get("memories", [])
            if isinstance(e, dict) and isinstance(e.get("ref_id"), str) and isinstance(e.get("content_hash"), str)
        }
        for ref_id in record.get("ref_ids", []):
            if not isinstance(ref_id, str):
                continue
            if ref_id not in order:
                order.append(ref_id)
            if ref_id in details:
                entries[ref_id] = details[ref_id]
    return order, entries


def legacy_owners(store: VectorStorePort) -> dict[str, str]:
    """Chunks from before 0.4, which carry no ``parent_ref``: each id a code record's ``chunk_refs`` lists, mapped to
    that record, a live one preferred where an old shared chunk has several (revalidation's ``referenced``)."""
    owners: dict[str, str] = {}
    records = store.list_all({"type": MemoryType.CODE.value}, include_content=False)
    for record in sorted(records, key=lambda m: m.retired()):  # live records first, so they win
        for chunk in record.chunk_refs:
            owners.setdefault(chunk, record.ref_id)
    return owners


def _owner_id(ref_id: str, memory: Memory | None, legacy: dict[str, str]) -> str | None:
    """A code chunk's file record: its ``parent_ref``; else a pre-0.4 owner whose ``chunk_refs`` lists it; else,
    when the chunk record is gone, the id's prefix."""
    if memory is not None and memory.parent_ref:
        return memory.parent_ref
    if ref_id in legacy and legacy[ref_id] != ref_id:
        return legacy[ref_id]
    if memory is None and CHUNK_INFIX in ref_id:
        return ref_id.rsplit(CHUNK_INFIX, 1)[0]
    return None


def _resolve(root: Path, source: str) -> Path | None:
    """``source`` inside the project root, as revalidation resolves it; None when it escapes the root."""
    root = root.resolve()
    candidate = Path(source) if Path(source).is_absolute() else root / source
    try:
        resolved = candidate.resolve()
    except OSError:
        return None
    return resolved if resolved.is_relative_to(root) else None


def _source_check(root: Path | None, source: str, expected: str, judged: Judged) -> None:
    """Add ``source changed`` when the file is gone or hashes differently from ``expected`` (no hash: gone only);
    without a root, only a note."""
    if root is None:
        judged.notes.append(NOTE_NO_ROOT)
        return
    path = _resolve(root, source)
    if path is None:
        judged.notes.append(NOTE_OUTSIDE_ROOT)
        return
    if not path.exists():
        judged.statuses.append(SOURCE_CHANGED)
        return
    if not expected:
        return  # a decision saved before source_hash existed, whose file is still there: nothing to compare
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        judged.notes.append(NOTE_UNREADABLE)
        return
    if compute_content_hash(text) != expected:
        judged.statuses.append(SOURCE_CHANGED)


def judge(
    store: VectorStorePort,
    settings: MemKernelSettings,
    ref_id: str,
    entry: dict[str, Any] | None,
    root: Path | None = None,
    legacy: dict[str, str] | None = None,
) -> Judged:
    """The statuses of one memory the run received (C3, C6), against the store now; every scope is read."""
    memory = store.get_by_id(ref_id)
    owner_id = _owner_id(ref_id, memory, legacy or {})
    subject = store.get_by_id(owner_id) if owner_id else memory  # a chunk is judged by its file record
    judged = Judged(ref_id, [], owner=owner_id or "")
    if subject is None or memory_is_expired(subject, settings):
        judged.statuses = [MISSING]
        return judged
    judged.source, judged.scope = subject.source, subject.scope
    if subject.superseded_by:
        judged.statuses.append(SUPERSEDED)
        judged.superseded_by = subject.superseded_by
    if subject.withdrawn_reason:
        judged.statuses.append(WITHDRAWN)
        judged.withdrawn_reason = subject.withdrawn_reason
    if entry is None:
        judged.statuses.append(UNKNOWN)
        return judged
    same_scheme = entry.get("content_hash_scheme", CONTENT_HASH_SCHEME) == CONTENT_HASH_SCHEME
    if not same_scheme:
        judged.statuses.append(REHASHED)
    elif memory is not None and memory.content_hash != entry["content_hash"]:
        judged.statuses.append(CHANGED)
    if entry.get("state") == recall_log.STATE_LIVE and subject.needs_review:
        judged.statuses.append(FLAGGED)
    source = subject.source if owner_id else str(entry.get("source") or subject.source)
    if source and subject.type in SOURCE_CHECKED_TYPES:
        if owner_id:
            expected = subject.content_hash  # made now, with the current scheme: C2 does not apply
        elif subject.type == MemoryType.CODE:
            expected = str(entry["content_hash"]) if same_scheme else ""
        else:
            expected = str(entry.get("source_hash") or "")
        _source_check(root, source, expected, judged)
    if not judged.statuses:
        judged.statuses = [UNCHANGED]
    return judged


def diff(
    settings: MemKernelSettings, run_id: str, store: VectorStorePort | None = None, root: Path | None = None
) -> dict[str, Any]:
    """The report for ``run_id``; ``records`` is 0 when no record carries it. ``root`` enables source checks."""
    records, unreadable = run_records(settings, run_id)
    notes = (
        [f"{unreadable} log file(s) could not be read and were skipped: the log is incomplete"] if unreadable else []
    )
    report: dict[str, Any] = {
        "run_id": run_id,
        "root": str(root) if root is not None else None,
        "records": len(records),
        "unreadable_log_files": unreadable,
        "memories": [],
        "counts": dict.fromkeys(STATUSES, 0),
        "notes": notes,
    }
    if not records:
        return report
    vector_store = store if store is not None else open_store(settings)
    try:
        legacy = legacy_owners(vector_store)
        order, entries = received(records)
        judged = [judge(vector_store, settings, ref_id, entries.get(ref_id), root, legacy) for ref_id in order]
    except STORE_ERRORS as exc:
        raise StoreUnavailableError(f"reading the store failed ({exc})") from exc
    cut = sum(1 for r in records if r.get("ref_ids_truncated") is True)
    if cut:
        notes.append(
            f"{cut} record(s) of this run had their ref_ids cut short: the run may have received memories not listed"
        )
    report["memories"] = [asdict(j) for j in judged]
    report["counts"] = {status: sum(status in j.statuses for j in judged) for status in STATUSES}
    return report


def render(report: dict[str, Any]) -> str:
    counts = ", ".join(f"{n} {status}" for status, n in report["counts"].items() if n)
    root = report["root"]
    lines = [
        f"Run {report['run_id']}: {len(report['memories'])} memory(ies) in {report['records']} record(s)"
        + (f": {counts}." if counts else "."),
        f"Root: {root}" if root else "Root: none given, so no source checks (pass root= in --store).",
    ]
    for m in report["memories"]:
        extra = [f"by {m['superseded_by']}" if m["superseded_by"] else "", m["withdrawn_reason"], *m["notes"]]
        detail = "; ".join(e for e in extra if e)
        where = f" ({m['source']})" if m["source"] else ""
        lines.append(f"- {m['ref_id']}{where}: {', '.join(m['statuses'])}" + (f" [{detail}]" if detail else ""))
    lines.extend(f"Note: {note}" for note in report["notes"])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument(
        "--store",
        required=True,
        help="name=…,chroma=…,state=…,project=…[,root=…]; root, the project that sources resolve under, enables "
        "the source checks",
    )
    parser.add_argument("--run", required=True, help="the run_id the harness passed to memkernel")
    parser.add_argument("--json", type=Path, help="also write the report as JSON")
    args = parser.parse_args(argv)
    settings, root = parse_store(args.store)
    try:
        report = diff(settings, args.run, store=open_store(settings), root=root)
    except StoreUnavailableError as exc:
        print(f"--store: {exc}", file=sys.stderr)
        return EXIT_USAGE
    if not report["records"]:
        incomplete = report["unreadable_log_files"]
        print(
            f"No recall-log record carries run_id {args.run!r} (a wrong id, or the log was off or rotated away)."
            + (f" {incomplete} log file(s) could not be read, so the log is incomplete." if incomplete else "")
        )
        return EXIT_NO_RECORDS
    print(render(report))
    if args.json:
        args.json.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return EXIT_REPORT


if __name__ == "__main__":
    raise SystemExit(main())

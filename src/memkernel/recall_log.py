# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""The recall log (memkernel-0-10-recall-log FR-001 to FR-004, #120): what each recall returned, and when.

Off unless ``MEMKERNEL_RECALL_LOG`` is set, because it stores query text. Each MCP ``recall`` appends one JSON line,
and so does each hook block that shows memories (amendment A1), under
``MEMKERNEL_STATE_DIR/recall-log/<project_id>/recall.jsonl``. Before an append that would pass
``recall_log_max_bytes`` the file is rotated (``recall.jsonl.1``, ``.2``, ...), keeping ``recall_log_max_files`` files;
a single record larger than the limit gives up query text first, then trailing ``memories`` details
(``memories_truncated``), then trailing ``ref_ids`` (``ref_ids_truncated``), and is marked ``truncated``;
``query_sha256`` always hashes the full query, so a record can be paired with its call either way.

Each record is also a context receipt (memkernel-0-15-harness-foundations FR-002, FR-003, A3): the run, agent and
task ids; per returned memory its ``content_hash`` with the hashing scheme, source, source hash and state; the
characters returned; and for an MCP recall its latency and the candidates excluded, by reason.
A write failure is logged once per process and never fails the recall. With an in-memory store there is no log.
The lock is POSIX-only (``fcntl``): on Windows the log runs unlocked, with one warning per process.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from memkernel import session_spool
from memkernel.core.models import SCOPE_PROJECT
from memkernel.memory.dedup import CONTENT_HASH_SCHEME
from memkernel.session_spool import locked

if TYPE_CHECKING:
    from collections.abc import Sequence

    from memkernel.config import MemKernelSettings
    from memkernel.core.models import Memory

logger = logging.getLogger(__name__)

RECALL_LOG_DIR = "recall-log"
RECALL_LOG_FILE = "recall.jsonl"
ORIGIN_TOOL = "tool"
ORIGIN_HOOK = "hook"
QUERY_MAX_CHARS = 2_000
FILE_MODE = 0o600
STATE_LIVE = "live"
STATE_FLAGGED = "flagged"

_warned = False
_warned_unlocked = False


def log_path(settings: MemKernelSettings) -> Path | None:
    """The project's current log file, or None when the log is off or the store is in memory."""
    if not settings.recall_log or not settings.chroma_persist_path.strip():
        return None
    return Path(settings.state_dir) / RECALL_LOG_DIR / settings.project_id / RECALL_LOG_FILE


def append(
    settings: MemKernelSettings,
    origin: str,
    ref_ids: Sequence[str],
    *,
    session_id: str = "",
    query: str = "",
    filters: dict[str, Any] | None = None,
    block: str = "",
    now: datetime | None = None,
    ids: Correlation | None = None,
    memories: Sequence[Memory] = (),
    returned_chars: int = 0,
    latency_ms: float | None = None,
    excluded: dict[str, int] | None = None,
    empty_reason: str | None = None,
) -> None:
    """Append one record; nothing when the log is off. Never raises: a failure is logged once per process.

    ``memories`` are the returned records in ``ref_ids`` order; ``ids`` default to the process's settings.
    ``latency_ms`` and ``excluded`` are left out of the record when None (a hook block, or ``order="newest"``);
    ``empty_reason`` (memkernel-0-15-harness-foundations B11) is written only for an empty recall.
    """
    path = log_path(settings)
    if path is None:
        return
    correlation = ids or Correlation.from_settings(settings)
    record: dict[str, Any] = {
        "time": (now or datetime.now(UTC)).isoformat(),
        "origin": origin,
        "session_id": session_id,
        "query": query[:QUERY_MAX_CHARS],
        "query_sha256": query_hash(query),
        "filters": filters or {},
        "ref_ids": list(ref_ids),
        "run_id": correlation.run_id,
        "agent_id": correlation.agent_id,
        "task_id": correlation.task_id,
        "memories": [receipt_entry(memory) for memory in memories],
        "returned_chars": returned_chars,
    }
    if block:
        record["block"] = block
    if latency_ms is not None:
        record["latency_ms"] = round(latency_ms, 3)
    if excluded is not None:
        record["excluded"] = dict(excluded)
    if empty_reason is not None:
        record["empty_reason"] = empty_reason
    line = _fit(record, settings.recall_log_max_bytes)
    if line is None:
        _warn_once(path, "a record does not fit in recall_log_max_bytes")
        return
    global _warned_unlocked
    if not session_spool.locking() and not _warned_unlocked:
        _warned_unlocked = True
        logger.warning("memkernel: recall log %s is not locked on this platform (no fcntl); writers may race", path)
    try:
        with locked(path):
            _rotate_if_needed(path, len(line), settings.recall_log_max_bytes, settings.recall_log_max_files)
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, FILE_MODE)
            with os.fdopen(descriptor, "ab") as handle:
                handle.write(line)
    except OSError as exc:
        _warn_once(path, str(exc))


@dataclass(frozen=True)
class Correlation:
    """The run, agent and task ids a record carries (FR-002): a call's own, or the process's settings."""

    run_id: str = ""
    agent_id: str = ""
    task_id: str = ""

    @classmethod
    def from_settings(cls, settings: MemKernelSettings) -> Correlation:
        return cls(settings.run_id, settings.agent_id, settings.task_id)


def receipt_entry(memory: Memory) -> dict[str, str]:
    """One returned memory as a receipt lists it (A3, A8): hashes and state, never content."""
    entry = {
        "ref_id": memory.ref_id,
        "content_hash": memory.content_hash,
        "content_hash_scheme": CONTENT_HASH_SCHEME,
        "state": STATE_FLAGGED if memory.needs_review else STATE_LIVE,
    }
    if memory.source:
        entry["source"] = memory.source
    if memory.source_hash:
        entry["source_hash"] = memory.source_hash
    if memory.scope != SCOPE_PROJECT:
        entry["scope"] = memory.scope  # B10: the log shows no agent received another agent's or task's record
    return entry


def _warn_once(path: Path, reason: str) -> None:
    global _warned
    if not _warned:
        _warned = True
        logger.warning("memkernel: recall log %s not written (%s); recalls continue unlogged", path, reason)


def _encode(record: dict[str, Any]) -> bytes:
    return (json.dumps(record, sort_keys=True) + "\n").encode("utf-8")


def query_hash(query: str) -> str:
    """The hash a record keeps of its full query; the count pairs records with transcript calls by it."""
    return hashlib.sha256(query.encode("utf-8")).hexdigest()


def _fit(record: dict[str, Any], max_bytes: int) -> bytes | None:
    """The record as one line within ``max_bytes``, cutting in order (A5): query text, then trailing ``memories``
    details, then trailing ref_ids, marking the record ``truncated``; None if even an empty query, no details and no
    ref_ids do not fit. Each cut is a binary search. ref_ids go last: the count relies on them."""
    line = _encode(record)
    if len(line) <= max_bytes:
        return line
    refs, details, query = list(record["ref_ids"]), list(record["memories"]), record["query"]

    def size(query_chars: int, detail_count: int, ref_count: int) -> int:
        trial = {
            **record,
            "query": query[:query_chars],
            "memories": details[:detail_count],
            "ref_ids": refs[:ref_count],
            "truncated": True,
        }
        return len(_encode(trial))

    keep_query, keep_details, keep_refs = len(query), len(details), len(refs)
    if size(0, keep_details, keep_refs) <= max_bytes:
        keep_query = _largest(lambda n: size(n, keep_details, keep_refs) <= max_bytes, len(query))
    elif size(0, 0, keep_refs) <= max_bytes:
        keep_query = 0
        keep_details = _largest(lambda n: size(0, n, keep_refs) <= max_bytes, len(details))
    else:
        keep_query, keep_details = 0, 0
        keep_refs = _largest(lambda n: size(0, 0, n) <= max_bytes, len(refs))
        if keep_refs < 0:
            return None
    fitted = {
        **record,
        "query": query[:keep_query],
        "memories": details[:keep_details],
        "ref_ids": refs[:keep_refs],
        "truncated": True,
    }
    if keep_details < len(details):
        fitted["memories_truncated"] = True
    if keep_refs < len(refs):
        fitted["ref_ids_truncated"] = True  # the count cannot take this record as proof that a memory was missed
    return _encode(fitted)


def _largest(fits: Any, upper: int) -> int:
    """The largest n in [0, upper] with fits(n), for a fits that holds up to some n and fails above it; -1 if none."""
    low, high = -1, upper
    while low < high:
        middle = (low + high + 1) // 2
        if fits(middle):
            low = middle
        else:
            high = middle - 1
    return low


def _rotate_if_needed(path: Path, incoming: int, max_bytes: int, max_files: int) -> None:
    """Shift ``recall.jsonl`` to ``.1`` (and older files up) when the next line would pass ``max_bytes``."""
    try:
        size = path.stat().st_size
    except FileNotFoundError:
        return
    if size == 0 or size + incoming <= max_bytes:
        return
    for index in range(max_files - 1, 0, -1):
        older = path.with_name(f"{path.name}.{index}")
        if index == max_files - 1:
            older.unlink(missing_ok=True)
        newer = path.with_name(f"{path.name}.{index - 1}") if index > 1 else path
        if newer.exists():
            newer.replace(older)
    if max_files == 1:
        path.unlink()

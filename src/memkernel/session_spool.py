# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""The session spool (memkernel-0-7-hooks H4, FR-008, FR-009): when Claude Code sessions started and ended.

The SessionStart hook appends a ``started`` line for every ``source`` and the SessionEnd hook an ``ended`` line,
one JSON object per line, under ``MEMKERNEL_STATE_DIR/session-spool/<project_id>/``. SessionEnd has a 1.5-second
budget, so writing a line imports only the settings: no store, no embedding model. The next ``startup`` drains
the spool: a session's window runs from its first ``started`` line to its last ``ended`` line, and a session that
saved no checkpoint inside its window is reported once. With an in-memory store there is no spool.

With capture on (memkernel-0-12-capture-core FR-001), the drain keeps ended sessions until capture commits them:
an unsaved one gets a ``reported`` line so it is reported once, and each failed read of its transcript a
``capture_missed`` line.
"""

from __future__ import annotations

import json
import logging
import os
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

try:
    import fcntl
except ImportError:  # not POSIX: appends and drains are not locked
    fcntl = None  # type: ignore[assignment]

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator

    from memkernel.config import MemKernelSettings

logger = logging.getLogger(__name__)

SPOOL_DIR = "session-spool"
SPOOL_FILE = "spool.jsonl"
EVENT_STARTED = "started"
EVENT_ENDED = "ended"
EVENT_REPORTED = "reported"  # an unsaved session already reported, kept for capture (FR-001)
EVENT_CAPTURE_MISSED = "capture_missed"  # one failed attempt to read the session's transcript (FR-008)
EVENTS = frozenset({EVENT_STARTED, EVENT_ENDED, EVENT_REPORTED, EVENT_CAPTURE_MISSED})
# A session with no ended line (a crash, or session-end.py not registered) is removed once its newest line is this
# old, so the spool stays bounded (memkernel-0-7-wiring-spool W2).
SPOOL_UNENDED_MAX_AGE = timedelta(days=7)


@dataclass(frozen=True)
class DrainResult:
    """What a drain found: ended sessions with no checkpoint in their window, and how many unended ones it pruned.

    ``ended`` is every ended session's window, the unsaved ones included; ``misses`` counts each one's
    ``capture_missed`` lines; ``ended_expired`` counts kept ended sessions removed after SPOOL_UNENDED_MAX_AGE.
    """

    unsaved: list[SessionWindow]
    unended_removed: int
    ended: list[SessionWindow] = field(default_factory=list)
    misses: dict[str, int] = field(default_factory=dict)
    ended_expired: int = 0


@dataclass(frozen=True)
class SessionWindow:
    """One ended session: from its first ``started`` line to its last ``ended`` line."""

    session_id: str
    start: datetime
    end: datetime
    reason: str
    transcript_path: str = ""


def spool_path(settings: MemKernelSettings) -> Path | None:
    """The project's spool file, or None for an in-memory store (empty ``chroma_persist_path``)."""
    if not settings.chroma_persist_path.strip():
        return None
    return Path(settings.state_dir) / SPOOL_DIR / settings.project_id / SPOOL_FILE


def append(settings: MemKernelSettings, event: str, session_id: str, when: datetime, **fields: str) -> None:
    """Append one line; nothing for an in-memory store or a payload without a session id."""
    path = spool_path(settings)
    if path is None or not session_id:
        return
    record = {"event": event, "session_id": session_id, "time": when.isoformat(), **fields}
    with locked(path), path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")


def drain(
    settings: MemKernelSettings,
    current_session_id: str | None,
    checkpointed: Callable[[SessionWindow], bool],
    now: datetime | None = None,
    keep_ended: bool = False,
) -> DrainResult:
    """Remove every ended session from the spool; report those that saved no checkpoint during their window.

    Kept: the current session's lines, and unended sessions whose newest line is younger than
    SPOOL_UNENDED_MAX_AGE. An older unended session is removed and counted (W2). An ended session with no
    ``started`` line has no known window: it is removed without a report. A malformed line is removed and logged
    once. A session with a ``reported`` line is never reported again.

    With ``keep_ended`` (capture on, FR-001), ended sessions stay until :func:`commit` removes them; an unsaved one
    gets a ``reported`` line. One whose end is older than SPOOL_UNENDED_MAX_AGE is removed and counted instead.
    """
    path = spool_path(settings)
    if path is None or not path.exists():
        return DrainResult([], 0)
    cutoff = (now or datetime.now(UTC)) - SPOOL_UNENDED_MAX_AGE
    with locked(path):
        records: list[dict[str, Any]] = []
        malformed = 0
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                record = json.loads(line)
                if datetime.fromisoformat(record["time"]).tzinfo is None:
                    raise ValueError("a time without a timezone")  # it could not be compared with the window
                if record["event"] not in EVENTS or not record["session_id"]:
                    raise ValueError(record["event"])
            except (ValueError, KeyError, TypeError):
                malformed += 1
                continue
            records.append(record)
        if malformed:
            logger.warning("session spool %s: %d malformed line(s) skipped and removed", path, malformed)
        by_session: dict[str, list[dict[str, Any]]] = {}
        for record in records:
            by_session.setdefault(record["session_id"], []).append(record)
        unsaved: list[SessionWindow] = []
        ended: list[SessionWindow] = []
        misses: dict[str, int] = {}
        kept: list[dict[str, Any]] = []
        unended_removed = ended_expired = 0
        for session_id, lines in by_session.items():
            starts = [datetime.fromisoformat(r["time"]) for r in lines if r["event"] == EVENT_STARTED]
            ends = [r for r in lines if r["event"] == EVENT_ENDED]
            if session_id == current_session_id:
                kept.extend(lines)
                continue
            if not ends:
                if max(datetime.fromisoformat(r["time"]) for r in lines) < cutoff:
                    unended_removed += 1  # its window never closed: no notice for it, only the count
                else:
                    kept.extend(lines)
                continue
            if not starts:
                continue  # an end without a start: the window is unknown
            last = max(ends, key=lambda r: datetime.fromisoformat(r["time"]))
            window = SessionWindow(
                session_id,
                min(starts),
                datetime.fromisoformat(last["time"]),
                str(last.get("reason", "")),
                str(last.get("transcript_path", "")),
            )
            if keep_ended and window.end < cutoff:
                ended_expired += 1  # never captured within the age limit: the spool stays bounded
                continue
            reported = any(r["event"] == EVENT_REPORTED for r in lines)
            if not reported and not checkpointed(window):
                unsaved.append(window)
                if keep_ended:
                    lines = [*lines, {"event": EVENT_REPORTED, "session_id": session_id, "time": _now(now)}]
            ended.append(window)
            misses[session_id] = sum(r["event"] == EVENT_CAPTURE_MISSED for r in lines)
            if keep_ended:
                kept.extend(lines)
        tmp = path.with_name(f"{path.name}.tmp")
        tmp.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in kept), encoding="utf-8")
        os.replace(tmp, path)
    return DrainResult(
        sorted(unsaved, key=lambda w: w.end),
        unended_removed,
        sorted(ended, key=lambda w: w.end),
        misses,
        ended_expired,
    )


def commit(settings: MemKernelSettings, session_ids: Iterable[str]) -> None:
    """Remove every line of ``session_ids`` from the spool, under the spool lock (FR-001, FR-002)."""
    path = spool_path(settings)
    gone = set(session_ids)
    if path is None or not gone or not path.exists():
        return
    with locked(path):
        lines = path.read_text(encoding="utf-8").splitlines()
        keep = [line for line in lines if _session_of(line) not in gone]
        tmp = path.with_name(f"{path.name}.tmp")
        tmp.write_text("".join(line + "\n" for line in keep), encoding="utf-8")
        os.replace(tmp, path)


def _session_of(line: str) -> str | None:
    try:
        record = json.loads(line)
    except ValueError:
        return None
    return str(record.get("session_id")) if isinstance(record, dict) else None


def _now(now: datetime | None) -> str:
    return (now or datetime.now(UTC)).isoformat()


def locking() -> bool:
    """Whether :func:`locked` really locks (POSIX ``fcntl``); on Windows it does not."""
    return fcntl is not None


@contextmanager
def locked(path: Path) -> Iterator[None]:
    """Hold an exclusive lock on ``<path>.lock`` (creating the directory); shared with the recall log."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_name(f"{path.name}.lock").open("a", encoding="utf-8") as handle:
        if fcntl is not None:
            fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(handle, fcntl.LOCK_UN)

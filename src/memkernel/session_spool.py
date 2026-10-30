# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""The session spool (memkernel-0-7-hooks H4, FR-008, FR-009): when Claude Code sessions started and ended.

The SessionStart hook appends a ``started`` line for every ``source`` and the SessionEnd hook an ``ended`` line,
one JSON object per line, under ``MEMKERNEL_STATE_DIR/session-spool/<project_id>/``. SessionEnd has a 1.5-second
budget, so writing a line imports only the settings: no store, no embedding model. The next ``startup`` drains
the spool: a session's window runs from its first ``started`` line to its last ``ended`` line, and a session that
saved no checkpoint inside its window is reported once. With an in-memory store there is no spool.
"""

from __future__ import annotations

import json
import logging
import os
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

try:
    import fcntl
except ImportError:  # not POSIX: appends and drains are not locked
    fcntl = None  # type: ignore[assignment]

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from memkernel.config import MemKernelSettings

logger = logging.getLogger(__name__)

SPOOL_DIR = "session-spool"
SPOOL_FILE = "spool.jsonl"
EVENT_STARTED = "started"
EVENT_ENDED = "ended"


@dataclass(frozen=True)
class SessionWindow:
    """One ended session: from its first ``started`` line to its last ``ended`` line."""

    session_id: str
    start: datetime
    end: datetime
    reason: str


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
    with _locked(path), path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")


def drain(
    settings: MemKernelSettings, current_session_id: str | None, checkpointed: Callable[[SessionWindow], bool]
) -> list[SessionWindow]:
    """Remove every ended session from the spool; return those that saved no checkpoint during their window.

    Kept: the current session's lines and sessions that have not ended. An ended session with no ``started``
    line has no known window: it is removed without a report. A malformed line is removed and logged once.
    """
    path = spool_path(settings)
    if path is None or not path.exists():
        return []
    with _locked(path):
        records: list[dict[str, Any]] = []
        malformed = 0
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                record = json.loads(line)
                datetime.fromisoformat(record["time"])
                if record["event"] not in (EVENT_STARTED, EVENT_ENDED) or not record["session_id"]:
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
        kept: list[dict[str, Any]] = []
        for session_id, lines in by_session.items():
            starts = [datetime.fromisoformat(r["time"]) for r in lines if r["event"] == EVENT_STARTED]
            ends = [r for r in lines if r["event"] == EVENT_ENDED]
            if session_id == current_session_id or not ends:
                kept.extend(lines)
                continue
            if not starts:
                continue  # an end without a start: the window is unknown
            last = max(ends, key=lambda r: datetime.fromisoformat(r["time"]))
            window = SessionWindow(
                session_id, min(starts), datetime.fromisoformat(last["time"]), str(last.get("reason", ""))
            )
            if not checkpointed(window):
                unsaved.append(window)
        tmp = path.with_name(f"{path.name}.tmp")
        tmp.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in kept), encoding="utf-8")
        os.replace(tmp, path)
    return sorted(unsaved, key=lambda w: w.end)


@contextmanager
def _locked(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_name(f"{path.name}.lock").open("a", encoding="utf-8") as handle:
        if fcntl is not None:
            fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(handle, fcntl.LOCK_UN)

# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""The recall log (memkernel-0-10-recall-log FR-001 to FR-004, #120): what each recall returned, and when.

Off unless ``MEMKERNEL_RECALL_LOG`` is set, because it stores query text. Each MCP ``recall`` appends one JSON line,
and so does each hook block that shows memories (amendment A1), under
``MEMKERNEL_STATE_DIR/recall-log/<project_id>/recall.jsonl``. Before an append that would pass
``recall_log_max_bytes`` the file is rotated (``recall.jsonl.1``, ``.2``, ...), keeping ``recall_log_max_files`` files.
A write failure is logged once per process and never fails the recall. With an in-memory store there is no log.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from memkernel.session_spool import locked

if TYPE_CHECKING:
    from collections.abc import Sequence

    from memkernel.config import MemKernelSettings

logger = logging.getLogger(__name__)

RECALL_LOG_DIR = "recall-log"
RECALL_LOG_FILE = "recall.jsonl"
ORIGIN_TOOL = "tool"
ORIGIN_HOOK = "hook"
QUERY_MAX_CHARS = 2_000
FILE_MODE = 0o600

_warned = False


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
) -> None:
    """Append one record; nothing when the log is off. Never raises: a failure is logged once per process."""
    path = log_path(settings)
    if path is None:
        return
    record: dict[str, Any] = {
        "time": (now or datetime.now(UTC)).isoformat(),
        "origin": origin,
        "session_id": session_id,
        "query": query[:QUERY_MAX_CHARS],
        "filters": filters or {},
        "ref_ids": list(ref_ids),
    }
    if block:
        record["block"] = block
    line = (json.dumps(record, sort_keys=True) + "\n").encode("utf-8")
    try:
        with locked(path):
            _rotate_if_needed(path, len(line), settings.recall_log_max_bytes, settings.recall_log_max_files)
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, FILE_MODE)
            with os.fdopen(descriptor, "ab") as handle:
                handle.write(line)
    except OSError as exc:
        global _warned
        if not _warned:
            _warned = True
            logger.warning("memkernel: recall log %s not written (%s); recalls continue unlogged", path, exc)


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

# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""``memkernel session-start``: the session-start block for coding tools other than Claude Code (#107 FR-003).

A tool's session-start hook runs ``memkernel session-start --format <tool>``. It reads the hook's JSON from stdin
when there is one (``source`` and a session id), runs :meth:`MemoryLifecycle.on_session_start`, and prints the block
in the shape the tool's hook expects. It writes nothing to the session spool: only Claude Code's hooks write both a
start and an end, and a start without an end would be reported as a session that "recorded no end" (FR-003).
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from typing import TYPE_CHECKING, Any

from memkernel.config import MemKernelSettings
from memkernel.lifecycle import SOURCE_STARTUP, STORED_CLOSE, STORED_NOTICE, STORED_OPEN, MemoryLifecycle

if TYPE_CHECKING:
    from collections.abc import Callable

    from memkernel.core.services import MemoryService

logger = logging.getLogger(__name__)

FORMAT_PLAIN = "plain"  # stdout text: Claude Code, Codex
FORMAT_CURSOR = "cursor"  # {"additional_context": ...}
FORMAT_ANTIGRAVITY = "antigravity"  # {"injectSteps": [{"systemMessage": ...}]}
FORMATS = (FORMAT_PLAIN, FORMAT_CURSOR, FORMAT_ANTIGRAVITY)
# The session id under the name each tool's hook payload uses (Claude Code and Codex, Cursor, Antigravity).
SESSION_ID_KEYS = ("session_id", "conversation_id", "conversationId")
CUT_NOTE = "(Cut to {limit} characters to fit this tool; use recall() or get(ref_id) for the rest.)"


def main(argv: list[str], build: Callable[[MemKernelSettings], MemoryService] | None = None) -> int:
    """Print the session-start block for ``--format``; exit 0 even on a failure, so the tool's session still starts."""
    parser = argparse.ArgumentParser(prog="memkernel session-start", description=__doc__.split("\n\n")[0])
    parser.add_argument("--format", choices=FORMATS, default=FORMAT_PLAIN, help="the hook output shape")
    parser.add_argument(
        "--max-chars",
        type=int,
        default=0,
        help="cut the block to this many characters; headings and the stored-memory notice are always kept",
    )
    args = parser.parse_args(argv)
    payload = _payload()
    source = _text(payload, "source") or SOURCE_STARTUP  # Cursor and Antigravity pass no source (FR-003)
    session_id = next((_text(payload, key) for key in SESSION_ID_KEYS if _text(payload, key)), None)
    try:
        settings = MemKernelSettings()
        if build is None:
            from memkernel.factory import build_service

            build = build_service
        text = MemoryLifecycle(build(settings), settings).on_session_start(source, session_id=session_id)
    except Exception:
        logger.warning("memkernel session-start failed; the session starts without memkernel's block", exc_info=True)
        text = ""
    if args.max_chars > 0:
        text = fit(text, args.max_chars)
    output = render(text, args.format)
    if output:
        print(output)
    return 0


def render(text: str, output_format: str) -> str:
    """The block in a tool's hook output shape; nothing to print for an empty block in plain text."""
    if output_format == FORMAT_CURSOR:
        return json.dumps({"additional_context": text}) if text else "{}"
    if output_format == FORMAT_ANTIGRAVITY:
        return json.dumps({"injectSteps": [{"systemMessage": text}]}) if text else "{}"
    return text


def fit(text: str, limit: int) -> str:
    """``text`` within ``limit`` characters, keeping every heading and whole stored-memory elements (FR-003, D5).

    Lines are kept in order while they fit; a heading and the stored-memory notice (#85) are always kept, and an
    element spanning lines is kept or dropped whole, so no element is left open. A note at the end says the block
    was cut.
    """
    if len(text) <= limit:
        return text
    note = CUT_NOTE.format(limit=limit)
    budget = limit - len(note) - 1
    kept: list[str] = []
    used = 0
    for unit in _units(text.splitlines()):
        size = len(unit) + 1
        if unit.startswith("#") or unit == STORED_NOTICE or used + size <= budget:
            kept.append(unit)
            used += size
    return "\n".join([*kept, note])


def _units(lines: list[str]) -> list[str]:
    """Lines grouped so a multi-line stored-memory element is one unit."""
    units: list[str] = []
    current: list[str] = []
    for line in lines:
        if current:
            current.append(line)
            if STORED_CLOSE in line:
                units.append("\n".join(current))
                current = []
        elif STORED_OPEN in line and STORED_CLOSE not in line:
            current = [line]
        else:
            units.append(line)
    if current:
        units.append("\n".join(current))
    return units


def _payload() -> dict[str, Any]:
    """The hook's stdin JSON; empty when stdin is a terminal, empty or not a JSON object."""
    if sys.stdin is None or sys.stdin.isatty():
        return {}
    try:
        data = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _text(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    return value if isinstance(value, str) else ""

#!/usr/bin/env python3
"""session-end.py — MemKernel SessionEnd hook.

Called by Claude Code when a session ends, with ``session_id``, ``reason`` and
``transcript_path`` in its stdin JSON. It appends one ``ended`` line to the
session spool in MEMKERNEL_STATE_DIR (``session-spool/<project_id>/``) and
nothing else: SessionEnd has a 1.5-second default budget, so it opens no store
and loads no embedding model. The next session's start reads the spool and
says when a session ended without saving a checkpoint (memkernel-0-7-hooks
D9). Claude Code discards SessionEnd output.

Prerequisites and installation are identical to session-start.py (the
`memkernel` package must be importable by the interpreter running this
script). Register under "SessionEnd" in .claude/settings.json:

    "hooks": {
      "SessionEnd": [{
        "matcher": "",
        "hooks": [{"type": "command", "command": "poetry run python .claude/hooks/session-end.py"}]
      }]
    }

Environment variables (all optional — defaults match server defaults):
    MEMKERNEL_PROJECT_ID           Project the spool belongs to (default: "default")
    MEMKERNEL_CHROMA_PERSIST_PATH  An empty value (in-memory store) means no spool
    MEMKERNEL_STATE_DIR            memkernel's state directory (default: ".memkernel/state")
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

# Allow running from a local checkout without `pip install`.
_REPO_SRC = Path(__file__).resolve().parent.parent.parent / "src"
if _REPO_SRC.is_dir() and str(_REPO_SRC) not in sys.path:
    sys.path.insert(0, str(_REPO_SRC))

from memkernel import session_spool  # noqa: E402
from memkernel.config import MemKernelSettings  # noqa: E402


def _payload() -> dict[str, object]:
    """The hook's stdin JSON; empty when stdin is a terminal (run by hand), empty or not a JSON object."""
    if sys.stdin is None or sys.stdin.isatty():
        return {}
    try:
        data = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _text(payload: dict[str, object], key: str) -> str:
    value = payload.get(key)
    return value if isinstance(value, str) else ""


def main() -> None:
    payload = _payload()
    session_spool.append(
        MemKernelSettings(),
        session_spool.EVENT_ENDED,
        _text(payload, "session_id"),
        datetime.now(UTC),
        reason=_text(payload, "reason"),
        transcript_path=_text(payload, "transcript_path"),
    )


if __name__ == "__main__":
    main()

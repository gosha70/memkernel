#!/usr/bin/env python3
"""post-compact.py — MemKernel PostCompact hook.

Called by Claude Code after context compaction, with ``compact_summary`` (the
summary the compaction produced), ``session_id`` and ``trigger`` in its stdin
JSON. It retains the summary as a checkpoint, so the next session starts from
it, and prints a status line to stderr. It prints nothing to stdout: Claude
Code does not add PostCompact output to the model's context. The recovery
after a compaction comes from session-start.py with ``source: "compact"``.

The whole protocol lives in ``memkernel.lifecycle.MemoryLifecycle``; this
script only reads its payload, builds the service and calls
``capture_compact_summary()``.

Prerequisites:
    `memkernel` (and its dependencies: chromadb, sentence-transformers, etc.) must
    be installed in the Python interpreter that runs this script.  The script imports
    those packages at startup; if they are missing you will see ModuleNotFoundError.

    Install memkernel in the target environment first:
        pip install memkernel          # or: poetry add memkernel / uv add memkernel

Install:
    Copy to .claude/hooks/post-compact.py and register in .claude/settings.json,
    referencing the Python interpreter that has memkernel installed:

    With Poetry (recommended for MemKernel projects):
        "command": "poetry run python .claude/hooks/post-compact.py"

    With uv:
        "command": "uv run python .claude/hooks/post-compact.py"

    With an explicit virtualenv:
        "command": "/path/to/.venv/bin/python .claude/hooks/post-compact.py"

    With system Python (only if memkernel is installed system-wide):
        "command": "python3 .claude/hooks/post-compact.py"

    Example settings.json entry (Poetry variant):

        "hooks": {
          "PostCompact": [{
            "matcher": "",
            "hooks": [{"type": "command", "command": "poetry run python .claude/hooks/post-compact.py"}]
          }]
        }

Environment variables (all optional — defaults match server defaults):
    MEMKERNEL_PROJECT_ID           Project to read from (default: "default")
    MEMKERNEL_CHROMA_PERSIST_PATH  ChromaDB data directory (default: ".memkernel/chroma")
    MEMKERNEL_EMBEDDING_MODEL      Embedding model name (default: "all-MiniLM-L6-v2")
    MEMKERNEL_PROJECT_ROOT         Directory code-memory sources resolve under (default: the hook's working directory)
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

# Allow running from a local checkout without `pip install`.
_REPO_SRC = Path(__file__).resolve().parent.parent.parent / "src"
if _REPO_SRC.is_dir() and str(_REPO_SRC) not in sys.path:
    sys.path.insert(0, str(_REPO_SRC))

from memkernel.factory import build_service  # noqa: E402
from memkernel.lifecycle import MemoryLifecycle  # noqa: E402

logging.basicConfig(stream=sys.stderr, level=logging.WARNING)
# Claude Code runs hooks from the project directory: make it the source root unless set.
os.environ.setdefault("MEMKERNEL_PROJECT_ROOT", os.getcwd())


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
    status = MemoryLifecycle(build_service()).capture_compact_summary(
        _text(payload, "compact_summary"), session_id=_text(payload, "session_id"), trigger=_text(payload, "trigger")
    )
    print(status, file=sys.stderr)


if __name__ == "__main__":
    main()

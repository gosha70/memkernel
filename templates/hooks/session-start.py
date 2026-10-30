#!/usr/bin/env python3
"""session-start.py — MemKernel SessionStart hook.

Called by Claude Code when a session starts, with ``source`` in its stdin
JSON. Claude Code adds this hook's stdout to the model's context:
- ``startup`` and ``clear``: the latest checkpoint, the most relevant long-term
  context and promotion candidates, after a consolidation pass;
- ``compact``: the recovery after a compaction (the latest checkpoint the agent
  saved, with its age, and long-term context; no consolidation);
- ``resume`` and ``fork``: nothing.
Register it without a matcher, so it runs for every ``source``.

The whole protocol lives in ``memkernel.lifecycle.MemoryLifecycle``; this
script only reads ``source``, builds the service and prints
``on_session_start(source)`` when it is not empty.

Prerequisites and installation are identical to pre-compact.py / post-compact.py
(the `memkernel` package must be importable by the interpreter running this
script). Register under "SessionStart" in .claude/settings.json:

    "hooks": {
      "SessionStart": [{
        "matcher": "",
        "hooks": [{"type": "command", "command": "poetry run python .claude/hooks/session-start.py"}]
      }]
    }

Environment variables (all optional — defaults match server defaults):
    MEMKERNEL_PROJECT_ID           Project to read from (default: "default")
    MEMKERNEL_CHROMA_PERSIST_PATH  ChromaDB data directory (default: ".memkernel/chroma")
    MEMKERNEL_EMBEDDING_MODEL      Embedding model name (default: "all-MiniLM-L6-v2")
    MEMKERNEL_PROJECT_ROOT         Directory code-memory sources resolve under (default: the hook's working directory)
    MEMKERNEL_WIKI_DIR             Optional LLM-wiki directory; its index.md is mentioned if present
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

from memkernel.config import MemKernelSettings  # noqa: E402
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
    source = _text(_payload(), "source") or None
    settings = MemKernelSettings()
    text = MemoryLifecycle(build_service(settings), settings).on_session_start(source)
    if text:
        print(text)


if __name__ == "__main__":
    main()

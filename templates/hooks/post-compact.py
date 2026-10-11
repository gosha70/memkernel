#!/usr/bin/env python3
"""post-compact.py — MemKernel PostCompact hook.

Called by Claude Code after context compaction.  Retrieves the most recent
checkpoint and a broader slice of long-term context, then writes recovered
content to stdout so Claude Code can inject it into the new session.

The whole protocol lives in ``memkernel.lifecycle.MemoryLifecycle``; this
script only builds the service and prints ``on_post_compact()``.

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
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

# Allow running from a local checkout without `pip install`.
_REPO_SRC = Path(__file__).resolve().parent.parent.parent / "src"
if _REPO_SRC.is_dir() and str(_REPO_SRC) not in sys.path:
    sys.path.insert(0, str(_REPO_SRC))

from memkernel.factory import build_service  # noqa: E402
from memkernel.lifecycle import MemoryLifecycle  # noqa: E402

logging.basicConfig(stream=sys.stderr, level=logging.WARNING)


def main() -> None:
    print(MemoryLifecycle(build_service()).on_post_compact())


if __name__ == "__main__":
    main()

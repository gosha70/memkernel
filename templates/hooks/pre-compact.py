#!/usr/bin/env python3
"""pre-compact.py — MemKernel PreCompact hook.

Called by Claude Code before context compaction. Its payload carries
``trigger`` and ``custom_instructions`` but no summary, so it retains no
checkpoint (the summary arrives in PostCompact); it runs a consolidation pass
and prints a status line to stderr. Its output never reaches the model.

The whole protocol lives in ``memkernel.lifecycle.MemoryLifecycle``; this
script only builds the service and calls ``on_pre_compact("")``.

Prerequisites:
    `memkernel` (and its dependencies: chromadb, sentence-transformers, etc.) must
    be installed in the Python interpreter that runs this script.  The script imports
    those packages at startup; if they are missing you will see ModuleNotFoundError.

    Install memkernel in the target environment first:
        pip install memkernel          # or: poetry add memkernel / uv add memkernel

Install:
    Copy to .claude/hooks/pre-compact.py and register in .claude/settings.json,
    referencing the Python interpreter that has memkernel installed:

    With Poetry (recommended for MemKernel projects):
        "command": "poetry run python .claude/hooks/pre-compact.py"

    With uv:
        "command": "uv run python .claude/hooks/pre-compact.py"

    With an explicit virtualenv:
        "command": "/path/to/.venv/bin/python .claude/hooks/pre-compact.py"

    With system Python (only if memkernel is installed system-wide):
        "command": "python3 .claude/hooks/pre-compact.py"

    Example settings.json entry (Poetry variant):

        "hooks": {
          "PreCompact": [{
            "matcher": "",
            "hooks": [{"type": "command", "command": "poetry run python .claude/hooks/pre-compact.py"}]
          }]
        }

    The hook uses the same MEMKERNEL_* environment variables as the server, so
    it connects to the same ChromaDB instance without going through the MCP
    transport (no HTTP session management required).

Environment variables (all optional — defaults match server defaults):
    MEMKERNEL_PROJECT_ID           Project to write into (default: "default")
    MEMKERNEL_CHROMA_PERSIST_PATH  ChromaDB data directory (default: ".memkernel/chroma")
    MEMKERNEL_EMBEDDING_MODEL      Embedding model name (default: "all-MiniLM-L6-v2")
    MEMKERNEL_PROJECT_ROOT         Directory code-memory sources resolve under (default: the hook's working directory)
"""

from __future__ import annotations

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


def main() -> None:
    # The PreCompact payload has no summary field (Claude Code hooks reference): nothing to read from stdin.
    print(MemoryLifecycle(build_service()).on_pre_compact(""), file=sys.stderr)


if __name__ == "__main__":
    main()

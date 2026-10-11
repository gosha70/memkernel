#!/usr/bin/env python3
"""session-start.py — MemKernel SessionStart hook.

Called by Claude Code when a session starts. Recovers the latest checkpoint
plus the most relevant long-term context and prints it to stdout so Claude
Code injects it into the new session. Also runs a consolidation pass so that
expired short-term memories are purged at the session boundary.

The whole protocol lives in ``memkernel.lifecycle.MemoryLifecycle``; this
script only builds the service and prints ``on_session_start()``.

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
    MEMKERNEL_WIKI_DIR             Optional LLM-wiki directory; its index.md is mentioned if present
"""

from __future__ import annotations

import logging
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


def main() -> None:
    settings = MemKernelSettings()
    print(MemoryLifecycle(build_service(settings), settings).on_session_start())


if __name__ == "__main__":
    main()

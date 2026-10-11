#!/usr/bin/env python3
"""pre-compact.py — MemKernel PreCompact hook.

Called by Claude Code before context compaction.  Reads the compaction event
from stdin (JSON), then stores a structured checkpoint in MemKernel so that
post-compaction recovery can restore session state.

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
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path

# Allow running from a local checkout without `pip install`.
_REPO_SRC = Path(__file__).resolve().parent.parent.parent / "src"
if _REPO_SRC.is_dir() and str(_REPO_SRC) not in sys.path:
    sys.path.insert(0, str(_REPO_SRC))

from memkernel.core.models import MemoryType  # noqa: E402
from memkernel.factory import build_service  # noqa: E402

logging.basicConfig(stream=sys.stderr, level=logging.WARNING)


def main() -> None:
    # Claude Code passes the compaction event as JSON on stdin.
    raw = sys.stdin.read().strip()
    event: dict[str, object] = json.loads(raw) if raw else {}
    summary = str(event.get("summary", "Compaction triggered — no summary provided."))

    now = datetime.now(UTC)
    session_id = now.strftime("checkpoint-%Y%m%d-%H%M%S")
    content = f"SESSION CHECKPOINT — {now.isoformat()}\n\n{summary}"

    svc = build_service()
    ref_id = svc.retain(
        content=content,
        type=MemoryType.EPISODE,
        checkpoint=True,
        session_id=session_id,
        importance=0.8,
        tags=["checkpoint"],
    )
    # Compaction is a natural consolidation point: purge decayed short-term
    # memories and surface what the agent kept using, so the post-compaction
    # context can suggest promoting it to long-term memory.
    report = svc.consolidate(limit=5)
    print(
        f"MemKernel: checkpoint retained — ref_id={ref_id}; purged={report['purged']} expired; "
        f"{len(report['candidates'])} promotion candidate(s)",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()

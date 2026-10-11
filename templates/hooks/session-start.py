#!/usr/bin/env python3
"""session-start.py — MemKernel SessionStart hook.

Called by Claude Code when a session starts. Recovers the latest checkpoint
plus the most relevant long-term context and prints it to stdout so Claude
Code injects it into the new session. Also runs a consolidation pass so that
expired short-term memories are purged at the session boundary.

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
from memkernel.core.models import MemoryTier  # noqa: E402
from memkernel.factory import build_service  # noqa: E402

logging.basicConfig(stream=sys.stderr, level=logging.WARNING)


def main() -> None:
    settings = MemKernelSettings()
    svc = build_service(settings)

    report = svc.consolidate(limit=5)

    checkpoint_refs = svc.recall("session checkpoint next steps", checkpoint_only=True, top_k=200, touch=False)
    checkpoint_refs.sort(key=lambda r: r.timestamp, reverse=True)
    latest = svc.get(checkpoint_refs[0].ref_id) if checkpoint_refs else None

    context_refs = svc.recall("decisions conventions active work", tier=MemoryTier.LONG_TERM, top_k=6)

    print("## Recovered from MemKernel (session start)\n")
    print("### Latest checkpoint")
    print(latest.content if latest is not None else "No checkpoint found yet.")

    print("\n### Long-term context")
    if context_refs:
        for r in context_refs:
            print(f"- [{r.type}] {r.preview}")
    else:
        print("No prior memories found.")

    if report["candidates"]:
        print("\n### Promotion candidates (short-term memories worth keeping)")
        for c in report["candidates"]:
            print(f"- {c['ref_id']} [{c['type']}, recalled {c['access_count']}x]: {c['preview']}")
        print("Call promote(ref_id, type, content) for anything that should outlive this session.")

    wiki_index = Path(settings.wiki_dir) / "index.md" if settings.wiki_dir else None
    if wiki_index is not None and wiki_index.is_file():
        print(f"\n### Wiki\nCurated knowledge lives in {wiki_index}; read it before re-deriving project context.")

    print("\n---")
    print(f"Purged {report['purged']} expired short-term memories. Use recall() / get(ref_id) for details.")


if __name__ == "__main__":
    main()

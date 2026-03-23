#!/usr/bin/env python3
"""post-compact.py — MemKernel PostCompact hook.

Called by Claude Code after context compaction.  Retrieves the most recent
checkpoint and a broader slice of long-term context, then writes recovered
content to stdout so Claude Code can inject it into the new session.

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

import chromadb  # noqa: E402
from chromadb.api import ClientAPI as ChromaClientAPI  # noqa: E402,TC002

from memkernel.config import MemKernelSettings  # noqa: E402
from memkernel.core.services import MemoryService  # noqa: E402
from memkernel.retrieval.chunking import ASTChunker  # noqa: E402
from memkernel.retrieval.embeddings import SentenceTransformerEmbedding  # noqa: E402
from memkernel.retrieval.search import HybridSearchService  # noqa: E402
from memkernel.retrieval.sparse import BM25Index  # noqa: E402
from memkernel.storage.chroma import ChromaVectorStore  # noqa: E402

logging.basicConfig(stream=sys.stderr, level=logging.WARNING)


def _build_service() -> MemoryService:
    settings = MemKernelSettings()
    persist = settings.chroma_persist_path
    client: ChromaClientAPI = chromadb.EphemeralClient() if not persist else chromadb.PersistentClient(path=persist)
    store = ChromaVectorStore(settings, client=client)
    embedding = SentenceTransformerEmbedding(settings)
    sparse = BM25Index()
    search_svc = HybridSearchService(store, embedding, sparse, settings)
    svc = MemoryService(store, embedding, sparse, search_svc, settings, chunker=ASTChunker(settings))
    svc.rebuild_sparse_index()
    return svc


def main() -> None:
    svc = _build_service()

    # Retrieve checkpoints with a large top_k so the subsequent timestamp sort
    # covers all real-world checkpoints — recall is relevance-ranked, not
    # recency-ranked, so a low top_k could exclude the newest checkpoint.
    checkpoint_refs = svc.recall(
        "session checkpoint decisions conventions next steps",
        checkpoint_only=True,
        top_k=200,
    )
    checkpoint_refs_sorted = sorted(checkpoint_refs, key=lambda r: r.timestamp, reverse=True)

    latest_checkpoint = ""
    if checkpoint_refs_sorted:
        mem = svc.get(checkpoint_refs_sorted[0].ref_id)
        if mem is not None:
            latest_checkpoint = mem.content

    # Broader long-term context (decisions + conventions, not checkpoint-filtered).
    context_refs = svc.recall(
        "decisions conventions architecture",
        top_k=5,
    )
    context_previews = "\n".join(f"- {r.preview}" for r in context_refs) if context_refs else ""

    # Output is injected by Claude Code into the new session's context.
    print("## Recovered from MemKernel (post-compaction)\n")

    if latest_checkpoint:
        print("### Latest checkpoint")
        print(latest_checkpoint)
    else:
        print("### Latest checkpoint")
        print("No checkpoint found. Use retain(checkpoint=true) before next compaction.")

    print("\n### Long-term context")
    if context_previews:
        print(context_previews)
    else:
        print("No prior memories found.")

    print("\n---")
    print("Use recall() for full content of any memory shown above.")


if __name__ == "__main__":
    main()

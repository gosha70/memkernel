# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""MemoryLifecycle — the session protocol as one Python component.

The Claude Code hook templates (``templates/hooks/``) and in-process
harnesses such as ``haa`` call the same four methods instead of
re-implementing the protocol described in ``docs/architecture/memory-tiers.md``
section 6:

* :meth:`MemoryLifecycle.on_session_start` — consolidate, recover the latest
  checkpoint and long-term context, list promotion candidates, point at the
  wiki index;
* :meth:`MemoryLifecycle.on_pre_compact` — retain a checkpoint episode from
  the compaction summary and run a consolidation pass;
* :meth:`MemoryLifecycle.on_post_compact` — re-inject the latest checkpoint,
  long-term context and promotion candidates;
* :meth:`MemoryLifecycle.on_session_end` — retain a session summary as a
  checkpoint and consolidate.

Every method returns markdown text ready for injection and performs no I/O
beyond the service: printing and stdin parsing stay in the caller.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from memkernel.config import MemKernelSettings
from memkernel.core.models import MemoryTier, MemoryType

if TYPE_CHECKING:
    from memkernel.core.models import ArtifactRef
    from memkernel.core.services import MemoryService

# Section headings are part of the hooks' stdout contract (FR-012): keep them stable.
HEADING_SESSION_START = "## Recovered from MemKernel (session start)"
HEADING_POST_COMPACT = "## Recovered from MemKernel (post-compaction)"
HEADING_SESSION_END = "## MemKernel session end"
HEADING_CHECKPOINT = "### Latest checkpoint"
HEADING_CONTEXT = "### Long-term context"
HEADING_CANDIDATES = "### Promotion candidates (short-term memories worth keeping)"
HEADING_NEEDS_REVIEW = "### Needs review"
HEADING_WIKI = "### Wiki"
SEPARATOR = "---"

CHECKPOINT_TAG = "checkpoint"
SESSION_END_TAG = "session-end"
CHECKPOINT_IMPORTANCE = 0.8
CANDIDATE_LIMIT = 5
# Checkpoints are relevance-ranked by recall; fetch many so the timestamp
# sort below sees every real-world checkpoint.
CHECKPOINT_FETCH = 200
SESSION_START_CONTEXT_TOP_K = 6
POST_COMPACT_CONTEXT_TOP_K = 5

_CHECKPOINT_PREFIX = "SESSION CHECKPOINT — "
_NO_SUMMARY = "Compaction triggered — no summary provided."
_PROMOTE_HINT = "Call promote(ref_id, type, content) for anything that should outlive this session."
_REVIEW_HINT = "These code memories no longer match their source; retain the file again as code to refresh them."


class MemoryLifecycle:
    """Session protocol over a :class:`~memkernel.core.services.MemoryService`."""

    def __init__(self, service: MemoryService, settings: MemKernelSettings | None = None) -> None:
        self._service = service
        self._settings = settings or MemKernelSettings()

    # ------------------------------------------------------------------
    # Session boundaries
    # ------------------------------------------------------------------

    def on_session_start(self) -> str:
        """Consolidate with revalidation; return checkpoint, context, candidates, review list and wiki pointer."""
        report = self._service.consolidate(limit=CANDIDATE_LIMIT, revalidate=True)
        latest = self._latest_checkpoint("session checkpoint next steps", touch=False)
        context = self._service.recall(
            "decisions conventions active work", tier=MemoryTier.LONG_TERM, top_k=SESSION_START_CONTEXT_TOP_K
        )
        lines = [
            HEADING_SESSION_START,
            "",
            HEADING_CHECKPOINT,
            latest if latest is not None else "No checkpoint found yet.",
            "",
            HEADING_CONTEXT,
            *(_context_lines(context) or ["No prior memories found."]),
        ]
        lines.extend(_candidates_block(report["candidates"]))
        lines.extend(_needs_review_block(report.get("revalidated", {}).get("flagged", [])))
        wiki_index = Path(self._settings.wiki_dir) / "index.md" if self._settings.wiki_dir else None
        if wiki_index is not None and wiki_index.is_file():
            lines.extend(
                [
                    "",
                    HEADING_WIKI,
                    f"Curated knowledge lives in {wiki_index}; read it before re-deriving project context.",
                ]
            )
        lines.extend(
            [
                "",
                SEPARATOR,
                f"Purged {report['purged']} expired short-term memories. Use recall() / get(ref_id) for details.",
            ]
        )
        return "\n".join(lines)

    def on_pre_compact(self, summary: str) -> str:
        """Retain ``summary`` as a checkpoint episode, consolidate, and return a one-line status."""
        now = datetime.now(UTC)
        ref_id = self._retain_checkpoint(summary or _NO_SUMMARY, now, [CHECKPOINT_TAG])
        report = self._service.consolidate(limit=CANDIDATE_LIMIT)
        return (
            f"MemKernel: checkpoint retained — ref_id={ref_id}; purged={report['purged']} expired; "
            f"{len(report['candidates'])} promotion candidate(s)"
        )

    def on_post_compact(self) -> str:
        """Return the latest checkpoint, long-term context and promotion candidates for re-injection."""
        latest = self._latest_checkpoint("session checkpoint decisions conventions next steps", touch=True)
        context = self._service.recall(
            "decisions conventions architecture", tier=MemoryTier.LONG_TERM, top_k=POST_COMPACT_CONTEXT_TOP_K
        )
        candidates = self._service.consolidate(limit=CANDIDATE_LIMIT, purge=False)["candidates"]
        lines = [
            HEADING_POST_COMPACT,
            "",
            HEADING_CHECKPOINT,
            latest
            if latest is not None
            else "No checkpoint found. Use retain(checkpoint=true) before next compaction.",
            "",
            HEADING_CONTEXT,
            *(_context_lines(context) or ["No prior memories found."]),
        ]
        lines.extend(_candidates_block(candidates))
        lines.extend(["", SEPARATOR, "Use recall() / get(ref_id) for full content of any memory shown above."])
        return "\n".join(lines)

    def on_session_end(self, summary: str) -> str:
        """Retain ``summary`` as a session checkpoint (if given), consolidate, and report what is worth promoting."""
        now = datetime.now(UTC)
        ref_id = self._retain_checkpoint(summary, now, [CHECKPOINT_TAG, SESSION_END_TAG]) if summary.strip() else None
        report = self._service.consolidate(limit=CANDIDATE_LIMIT)
        lines = [
            HEADING_SESSION_END,
            "",
            f"Session summary retained as checkpoint — ref_id={ref_id}" if ref_id else "No session summary retained.",
        ]
        lines.extend(_candidates_block(report["candidates"]))
        lines.extend(["", SEPARATOR, f"Purged {report['purged']} expired short-term memories."])
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _retain_checkpoint(self, summary: str, now: datetime, tags: list[str]) -> str:
        return self._service.retain(
            content=f"{_CHECKPOINT_PREFIX}{now.isoformat()}\n\n{summary}",
            type=MemoryType.EPISODE,
            checkpoint=True,
            session_id=now.strftime("checkpoint-%Y%m%d-%H%M%S"),
            importance=CHECKPOINT_IMPORTANCE,
            tags=tags,
        )

    def _latest_checkpoint(self, query: str, touch: bool) -> str | None:
        refs = self._service.recall(query, checkpoint_only=True, top_k=CHECKPOINT_FETCH, touch=touch)
        if not refs:
            return None
        newest = max(refs, key=lambda r: r.timestamp)
        memory = self._service.get(newest.ref_id)
        return memory.content if memory is not None else None


def _context_lines(refs: list[ArtifactRef]) -> list[str]:
    return [f"- [{r.type}] {r.preview}" for r in refs]


def _needs_review_block(flagged: list[dict[str, Any]]) -> list[str]:
    if not flagged:
        return []
    return [
        "",
        HEADING_NEEDS_REVIEW,
        *(f"- {f['source']} — {f['reason']} — {f['ref_id']}" for f in flagged),
        _REVIEW_HINT,
    ]


def _candidates_block(candidates: list[dict[str, Any]]) -> list[str]:
    if not candidates:
        return []
    return [
        "",
        HEADING_CANDIDATES,
        *(f"- {c['ref_id']} [{c['type']}, recalled {c['access_count']}x]: {c['preview']}" for c in candidates),
        _PROMOTE_HINT,
    ]

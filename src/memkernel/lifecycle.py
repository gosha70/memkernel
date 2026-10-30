# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""MemoryLifecycle — the session protocol as one Python component.

The Claude Code hook templates (``templates/hooks/``) and in-process
harnesses such as ``haa`` call the same four methods instead of
re-implementing the protocol described in ``docs/architecture/memory-tiers.md``
section 6:

* :meth:`MemoryLifecycle.on_session_start` — by ``source``: consolidate, recover the
  latest checkpoint and long-term context, list promotion candidates, point at
  the wiki index (``startup``, ``clear``); a short recovery block after a
  compaction (``compact``); nothing on ``resume`` or ``fork``;
* :meth:`MemoryLifecycle.on_pre_compact` — retain a checkpoint episode from
  a compaction summary, when one is given, and run a consolidation pass;
* :meth:`MemoryLifecycle.capture_compact_summary` — retain Claude Code's own
  compaction summary (the PostCompact payload's ``compact_summary``);
* :meth:`MemoryLifecycle.on_post_compact` — re-inject the latest checkpoint,
  long-term context and promotion candidates;
* :meth:`MemoryLifecycle.on_session_end` — retain a session summary as a
  checkpoint and consolidate.

Every method returns markdown text ready for injection and performs no I/O
beyond the service: printing and stdin parsing stay in the caller.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
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
HEADING_STORE_HEALTH = "### Store health"
HEADING_WIKI = "### Wiki"
SEPARATOR = "---"

CHECKPOINT_TAG = "checkpoint"
SESSION_END_TAG = "session-end"
COMPACT_SUMMARY_TAG = "compact-summary"  # a checkpoint captured from Claude Code's own compaction summary
SESSION_TAG_PREFIX = "session:"
# SessionStart ``source`` values (Claude Code hooks reference): the full block for the rest, including ``clear``.
SOURCE_COMPACT = "compact"
SOURCES_ALREADY_IN_CONTEXT = frozenset({"resume", "fork"})
CHECKPOINT_IMPORTANCE = 0.8
CANDIDATE_LIMIT = 5
SESSION_START_CONTEXT_TOP_K = 6
POST_COMPACT_CONTEXT_TOP_K = 5

_CHECKPOINT_PREFIX = "SESSION CHECKPOINT — "
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

    def on_session_start(self, source: str | None = None) -> str:
        """The SessionStart block for ``source``.

        ``resume`` and ``fork``: an empty string (the context already holds it). ``compact``: the recovery block of
        :meth:`_compact_recovery`. Anything else, ``None`` included: consolidate with revalidation and return the
        checkpoint, context, candidates, review list and wiki pointer. ``clear`` gets that full block on purpose: it
        empties the conversation like a new session.
        """
        if source in SOURCES_ALREADY_IN_CONTEXT:
            return ""
        if source == SOURCE_COMPACT:
            return self._compact_recovery()
        report = self._service.consolidate(limit=CANDIDATE_LIMIT, revalidate=True)
        latest = self._latest_checkpoint()
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
        lines.extend(_store_health_block(report.get("health", {})))
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
        """Retain a non-empty ``summary`` as a checkpoint episode, consolidate, and return a one-line status.

        A blank summary retains nothing: a placeholder would become the newest checkpoint and hide a real one.
        """
        ref_id = self._retain_checkpoint(summary, datetime.now(UTC), [CHECKPOINT_TAG]) if summary.strip() else None
        report = self._service.consolidate(limit=CANDIDATE_LIMIT)
        retained = f"checkpoint retained — ref_id={ref_id}" if ref_id else "no summary given; nothing retained"
        return (
            f"MemKernel: {retained}; purged={report['purged']} expired; "
            f"{len(report['candidates'])} promotion candidate(s)"
        )

    def capture_compact_summary(self, summary: str, session_id: str = "", trigger: str = "") -> str:
        """Retain Claude Code's compaction summary as a checkpoint tagged ``compact-summary``; return a status line.

        It is the newest checkpoint for the next session's start, and is left out of the ``compact`` recovery block,
        whose context already holds it. A blank summary retains nothing.
        """
        if not summary.strip():
            return "MemKernel: the compaction carried no summary; nothing retained"
        tags = [CHECKPOINT_TAG, COMPACT_SUMMARY_TAG]
        if session_id:
            tags.append(f"{SESSION_TAG_PREFIX}{session_id}")
        ref_id = self._retain_checkpoint(summary, datetime.now(UTC), tags)
        how = f" ({trigger})" if trigger else ""
        return f"MemKernel: compaction summary{how} retained as a checkpoint — ref_id={ref_id}"

    def on_post_compact(self) -> str:
        """Return the latest checkpoint, long-term context and promotion candidates for re-injection."""
        latest = self._latest_checkpoint()
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

    def _compact_recovery(self) -> str:
        """After a compaction: the latest checkpoint not captured from the compaction summary, with its age, and the
        long-term context. No consolidation, revalidation, purge or candidates; the same whichever hook ran first."""
        chosen = next((m for m in self._service.checkpoints_newest_first() if COMPACT_SUMMARY_TAG not in m.tags), None)
        checkpoint = self._service.get(chosen.ref_id, touch=False) if chosen is not None else None
        context = self._service.recall(
            "decisions conventions architecture", tier=MemoryTier.LONG_TERM, top_k=POST_COMPACT_CONTEXT_TOP_K
        )
        lines = [HEADING_POST_COMPACT, "", HEADING_CHECKPOINT]
        if checkpoint is None:
            lines.append("No checkpoint found.")
        else:
            saved = checkpoint.timestamp.astimezone(UTC)
            lines.append(
                f"Saved {_age(datetime.now(UTC) - saved)} ago ({saved.strftime('%Y-%m-%d %H:%M UTC')}); "
                "it may predate this session's work."
            )
            lines.append(checkpoint.content)
        lines.extend(["", HEADING_CONTEXT, *(_context_lines(context) or ["No prior memories found."])])
        lines.extend(["", SEPARATOR, "Use recall() / get(ref_id) for full content of any memory shown above."])
        return "\n".join(lines)

    def _latest_checkpoint(self) -> str | None:
        """The newest live checkpoint's content (by time over every live checkpoint, never a relevance window).

        Reading it counts as one access, on that checkpoint only; before 0.6 ``on_post_compact`` also touched every
        checkpoint its recall returned.
        """
        checkpoints = self._service.checkpoints_newest_first()
        if not checkpoints:
            return None
        memory = self._service.get(checkpoints[0].ref_id)
        return memory.content if memory is not None else None


def _age(delta: timedelta) -> str:
    """``delta`` in whole minutes under an hour, hours under two days, days otherwise."""
    minutes = max(0, int(delta.total_seconds() // 60))
    if minutes < 60:
        value, unit = minutes, "minute"
    elif minutes < 48 * 60:
        value, unit = minutes // 60, "hour"
    else:
        value, unit = minutes // (24 * 60), "day"
    return f"{value} {unit}{'' if value == 1 else 's'}"


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


_HEALTH_LABELS: tuple[tuple[str, str], ...] = (
    ("orphans", "orphans"),
    ("dangling_links", "dangling links"),
    ("unmarked_supersessions", "unmarked supersessions"),
    ("stale_sources", "stale sources"),
    ("needs_review", "needs review"),
    ("expired_present", "expired"),
)


def _store_health_block(summary: dict[str, int]) -> list[str]:
    if not any(summary.get(key, 0) for key, _ in _HEALTH_LABELS):
        return []
    return ["", HEADING_STORE_HEALTH, ", ".join(f"{label} {summary.get(key, 0)}" for key, label in _HEALTH_LABELS)]


def _candidates_block(candidates: list[dict[str, Any]]) -> list[str]:
    if not candidates:
        return []
    return [
        "",
        HEADING_CANDIDATES,
        *(f"- {c['ref_id']} [{c['type']}, recalled {c['access_count']}x]: {c['preview']}" for c in candidates),
        _PROMOTE_HINT,
    ]

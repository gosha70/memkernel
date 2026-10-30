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

from memkernel import session_spool
from memkernel.config import MemKernelSettings
from memkernel.core.models import MemoryTier, MemoryType

if TYPE_CHECKING:
    from memkernel.core.models import ArtifactRef, Memory
    from memkernel.core.services import MemoryService
    from memkernel.session_spool import SessionWindow

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
HEADING_PREVIOUS_SESSIONS = "### Previous sessions"
SEPARATOR = "---"

CHECKPOINT_TAG = "checkpoint"
SESSION_END_TAG = "session-end"
COMPACT_SUMMARY_TAG = "compact-summary"  # a checkpoint captured from Claude Code's own compaction summary
SESSION_TAG_PREFIX = "session:"
# SessionStart ``source`` values (Claude Code hooks reference): the full block for the rest, including ``clear``.
SOURCE_COMPACT = "compact"
SOURCE_STARTUP = "startup"
SOURCES_ALREADY_IN_CONTEXT = frozenset({"resume", "fork"})
CHECKPOINT_IMPORTANCE = 0.8
CANDIDATE_LIMIT = 5
SESSION_START_CONTEXT_TOP_K = 6
POST_COMPACT_CONTEXT_TOP_K = 5
# Startup context without a query (memkernel-0-7-hooks H1): these types first, in this order, then the rest.
CONTEXT_TYPE_ORDER = (MemoryType.DECISION, MemoryType.CONVENTION, MemoryType.PROCEDURE, MemoryType.FACT)
# Output budget (FR-003): Claude Code caps injected hook output at 10,000 characters; each hook's block stays under
# TOTAL_BUDGET, with these shares. The remainder covers headings, health, the wiki pointer and the footer. Release
# B part 2c's curation debt must take its share from here, never add to the total.
TOTAL_BUDGET = 9_000
CHECKPOINT_BUDGET = 3_500
CONTEXT_BUDGET = 2_500
CANDIDATES_BUDGET = 1_200
NEEDS_REVIEW_BUDGET = 1_000
NEEDS_REVIEW_MAX_LINES = 10
PREVIOUS_SESSIONS_MAX_LINES = 3

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

    def on_session_start(self, source: str | None = None, session_id: str | None = None) -> str:
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
        unsaved = self._drain_spool(session_id) if source == SOURCE_STARTUP else []
        report = self._service.consolidate(limit=CANDIDATE_LIMIT, revalidate=True)
        latest = self._latest_checkpoint_memory()
        context = _distinct(self._startup_context(), latest, SESSION_START_CONTEXT_TOP_K)
        lines = [
            HEADING_SESSION_START,
            "",
            HEADING_CHECKPOINT,
            *(self._checkpoint_lines(latest) if latest is not None else ["No checkpoint found yet."]),
            *_previous_sessions_block(unsaved),
            "",
            HEADING_CONTEXT,
            *(self._memory_lines(context) or ["No prior memories found."]),
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
        return _cap("\n".join(lines))

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
        if checkpoint is not None:  # H1: the work in progress is the query
            refs = self._service.recall(
                checkpoint.content, tier=MemoryTier.LONG_TERM, top_k=2 * POST_COMPACT_CONTEXT_TOP_K, touch=False
            )
            found = [self._service.get(r.ref_id, touch=False) for r in refs]
            candidates = [m for m in found if m is not None]
        else:
            candidates = self._startup_context()
        context = _distinct(candidates, checkpoint, POST_COMPACT_CONTEXT_TOP_K)
        lines = [HEADING_POST_COMPACT, "", HEADING_CHECKPOINT]
        lines.extend(self._checkpoint_lines(checkpoint) if checkpoint is not None else ["No checkpoint found."])
        lines.extend(["", HEADING_CONTEXT, *(self._memory_lines(context) or ["No prior memories found."])])
        lines.extend(["", SEPARATOR, "Use recall() / get(ref_id) for full content of any memory shown above."])
        return _cap("\n".join(lines))

    def _drain_spool(self, session_id: str | None) -> list[SessionWindow]:
        """Ended sessions that saved no checkpoint during their window (memkernel-0-7-hooks FR-009).

        Any checkpoint saved in the window counts, live or not: one since expired, superseded or withdrawn was
        still saved during that session. ``list_memories(include_superseded=True)`` returns retired records and
        applies no expiry filter, and the drain runs before startup's consolidation purges expired records.
        """
        checkpoints = [m for m in self._service.list_memories(include_superseded=True) if m.checkpoint]

        def checkpointed(window: SessionWindow) -> bool:
            tag = f"{SESSION_TAG_PREFIX}{window.session_id}"
            return any(window.start <= m.timestamp <= window.end or tag in m.tags for m in checkpoints)

        return session_spool.drain(self._settings, session_id, checkpointed)

    def _startup_context(self) -> list[Memory]:
        """Live long-term memories without a query: by type (CONTEXT_TYPE_ORDER), importance, recency (H1)."""
        rank = {t: i for i, t in enumerate(CONTEXT_TYPE_ORDER)}
        memories = [m for m in self._service.list_memories(tier=MemoryTier.LONG_TERM) if m.parent_ref is None]
        return sorted(
            memories,
            key=lambda m: (rank.get(m.type, len(rank)), -m.importance, -m.timestamp.timestamp(), m.ref_id),
        )

    def _latest_checkpoint_memory(self) -> Memory | None:
        """The newest live checkpoint, read with one access (memkernel-0-6-compaction-hooks FR-011)."""
        checkpoints = self._service.checkpoints_newest_first()
        return self._service.get(checkpoints[0].ref_id) if checkpoints else None

    def _checkpoint_lines(self, checkpoint: Memory) -> list[str]:
        """The age line with the checkpoint's ref_id (FR-001), then its text within CHECKPOINT_BUDGET (FR-003)."""
        saved = checkpoint.timestamp.astimezone(UTC)
        age = (
            f"Saved {_age(datetime.now(UTC) - saved)} ago ({saved.strftime('%Y-%m-%d %H:%M UTC')}, "
            f"{checkpoint.ref_id}); it may predate this session's work."
        )
        return [age, _truncate(checkpoint.content, CHECKPOINT_BUDGET, checkpoint.ref_id)]

    def _memory_lines(self, memories: list[Memory]) -> list[str]:
        preview = self._service.settings.preview_length
        lines = [f"- [{m.type}] {' '.join(m.content.split())[:preview]} ({m.ref_id})" for m in memories]
        return _fit(lines, CONTEXT_BUDGET)

    def _latest_checkpoint(self) -> str | None:
        """The newest live checkpoint's content (by time over every live checkpoint, never a relevance window).

        Reading it counts as one access, on that checkpoint only; before 0.6 ``on_post_compact`` also touched every
        checkpoint its recall returned.
        """
        memory = self._latest_checkpoint_memory()
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
    return _fit([f"- [{r.type}] {r.preview} ({r.ref_id})" for r in refs], CONTEXT_BUDGET)


def _previous_sessions_block(unsaved: list[SessionWindow]) -> list[str]:
    """One line per ended session with no checkpoint during it (H4), within PREVIOUS_SESSIONS_MAX_LINES."""
    if not unsaved:
        return []
    shown = unsaved[-PREVIOUS_SESSIONS_MAX_LINES:]
    lines = [
        f"The previous session ({w.reason or 'ended'}, {w.end.astimezone(UTC).strftime('%Y-%m-%d %H:%M UTC')}) "
        "ended without a saved checkpoint."
        for w in shown
    ]
    if len(unsaved) > len(shown):
        lines.insert(0, f"… and {len(unsaved) - len(shown)} earlier session(s) the same")
    return ["", HEADING_PREVIOUS_SESSIONS, *lines]


def _distinct(candidates: list[Memory], checkpoint: Memory | None, limit: int) -> list[Memory]:
    """FR-004: no item equal to the checkpoint or an earlier item (ref_id or content hash), and no live source of
    a promoted memory that is also shown; then the first ``limit``."""
    seen_refs = {checkpoint.ref_id} if checkpoint is not None else set()
    seen_hashes = {checkpoint.content_hash} if checkpoint is not None and checkpoint.content_hash else set()
    kept: list[Memory] = []
    for memory in candidates:
        if memory.ref_id in seen_refs or (memory.content_hash and memory.content_hash in seen_hashes):
            continue
        seen_refs.add(memory.ref_id)
        if memory.content_hash:
            seen_hashes.add(memory.content_hash)
        kept.append(memory)
    promoted_sources = {m.promoted_from for m in kept if m.promoted_from}
    return [m for m in kept if m.ref_id not in promoted_sources][:limit]


def _fit(lines: list[str], budget: int) -> list[str]:
    """The leading ``lines`` that fit in ``budget`` characters, then one line saying how many were left out."""
    kept: list[str] = []
    used = 0
    for line in lines:
        if used + len(line) + 1 > budget:
            return [*kept, f"… and {len(lines) - len(kept)} more (use recall() for the rest)"]
        kept.append(line)
        used += len(line) + 1
    return kept


def _truncate(text: str, budget: int, ref_id: str) -> str:
    """``text`` cut at a line boundary within ``budget`` characters, saying where the rest is (FR-003)."""
    if len(text) <= budget:
        return text
    suffix = f"… (truncated; get({ref_id}) for the rest)"
    cut = text[: max(0, budget - len(suffix) - 1)]
    cut = cut[: cut.rfind("\n")] if "\n" in cut else cut
    return f"{cut}\n{suffix}"


def _cap(block: str) -> str:
    """The whole block under TOTAL_BUDGET: a last guard behind the section shares (FR-003)."""
    if len(block) <= TOTAL_BUDGET:
        return block
    suffix = "… (truncated to stay under Claude Code's hook output limit)"
    cut = block[: TOTAL_BUDGET - len(suffix) - 1]
    return f"{cut[: cut.rfind(chr(10))]}\n{suffix}"


def _needs_review_block(flagged: list[dict[str, Any]]) -> list[str]:
    if not flagged:
        return []
    shown = flagged[:NEEDS_REVIEW_MAX_LINES]
    lines = [f"- {f['source']} — {f['reason']} — {f['ref_id']}" for f in shown]
    if len(flagged) > len(shown):
        lines.append(f"… and {len(flagged) - len(shown)} more (consolidate(revalidate=true) lists all)")
    return ["", HEADING_NEEDS_REVIEW, *_fit(lines, NEEDS_REVIEW_BUDGET), _REVIEW_HINT]


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
        *_fit(
            [f"- {c['ref_id']} [{c['type']}, recalled {c['access_count']}x]: {c['preview']}" for c in candidates],
            CANDIDATES_BUDGET,
        ),
        _PROMOTE_HINT,
    ]

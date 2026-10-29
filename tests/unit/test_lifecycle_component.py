"""Unit tests for MemoryLifecycle (US4, FR-011): all four session-protocol methods."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

import chromadb
import pytest

from memkernel.config import MemKernelSettings
from memkernel.core.models import MemoryType
from memkernel.factory import build_service
from memkernel.lifecycle import (
    HEADING_CANDIDATES,
    HEADING_CHECKPOINT,
    HEADING_CONTEXT,
    HEADING_POST_COMPACT,
    HEADING_SESSION_END,
    HEADING_SESSION_START,
    HEADING_WIKI,
    MemoryLifecycle,
)
from tests.conftest import MockEmbedding

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit


def _settings(**overrides: Any) -> MemKernelSettings:
    base: dict[str, Any] = {"project_id": f"lc-{uuid.uuid4().hex[:8]}", "chroma_persist_path": ""}
    base.update(overrides)
    return MemKernelSettings(**base)


def _lifecycle(**overrides: Any) -> tuple[MemoryLifecycle, Any]:
    settings = _settings(**overrides)
    svc = build_service(settings, embedding=MockEmbedding(), chroma_client=chromadb.EphemeralClient())
    return MemoryLifecycle(svc, settings), svc


def test_session_start_on_empty_store_has_the_0_2_headings() -> None:
    lifecycle, _ = _lifecycle()
    text = lifecycle.on_session_start()
    assert text.splitlines()[0] == HEADING_SESSION_START
    assert f"{HEADING_CHECKPOINT}\nNo checkpoint found yet." in text
    assert f"{HEADING_CONTEXT}\nNo prior memories found." in text
    assert HEADING_CANDIDATES not in text
    assert HEADING_WIKI not in text
    assert text.endswith("---\nPurged 0 expired short-term memories. Use recall() / get(ref_id) for details.")


def test_session_start_recovers_checkpoint_context_and_candidates(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    (wiki / "index.md").write_text("# index\n")
    lifecycle, svc = _lifecycle(wiki_dir=str(wiki))
    svc.retain("Use arq for background jobs", MemoryType.DECISION)
    obs = svc.retain("pytest needs MEMKERNEL_PROJECT_ID", MemoryType.OBSERVATION)
    svc.get(obs)
    svc.retain("SESSION CHECKPOINT old\n\nNext: a", MemoryType.EPISODE, checkpoint=True)
    newest = svc.retain("SESSION CHECKPOINT new\n\nNext: b", MemoryType.EPISODE, checkpoint=True)

    text = lifecycle.on_session_start()
    assert "SESSION CHECKPOINT new" in text
    assert "SESSION CHECKPOINT old" not in text
    assert "- [decision] Use arq for background jobs" in text
    assert HEADING_CANDIDATES in text
    assert f"- {obs} [observation, recalled 1x]: pytest needs MEMKERNEL_PROJECT_ID" in text
    assert "Call promote(ref_id, type, content)" in text
    assert f"{HEADING_WIKI}\nCurated knowledge lives in {wiki / 'index.md'}" in text
    # recall(touch=False) leaves the checkpoint alone; only the get() that reads it counts as an access (as in 0.2)
    memory = svc.get(newest, touch=False)
    assert memory is not None and memory.access_count == 1


def test_pre_compact_retains_checkpoint_and_reports() -> None:
    lifecycle, svc = _lifecycle()
    svc.retain("something observed", MemoryType.OBSERVATION)
    status = lifecycle.on_pre_compact("Done: X\nNext: Y")
    assert status.startswith("MemKernel: checkpoint retained — ref_id=")
    assert status.endswith("purged=0 expired; 1 promotion candidate(s)")
    ref_id = status.split("ref_id=")[1].split(";")[0]
    memory = svc.get(ref_id, touch=False)
    assert memory is not None
    assert memory.checkpoint is True
    assert memory.type == MemoryType.EPISODE
    assert memory.importance == 0.8
    assert memory.tags == ["checkpoint"]
    assert memory.session_id.startswith("checkpoint-")
    assert memory.content.startswith("SESSION CHECKPOINT — ") and memory.content.endswith("\n\nDone: X\nNext: Y")


def test_pre_compact_without_summary_retains_nothing() -> None:
    """D1 (memkernel-0-6-compaction-hooks FR-001): no placeholder, so no fake newest checkpoint."""
    lifecycle, svc = _lifecycle()
    status = lifecycle.on_pre_compact("  ")
    assert status.startswith("MemKernel: no summary given; nothing retained; purged=0 expired")
    assert svc.recall("checkpoint", checkpoint_only=True, touch=False) == []


def test_post_compact_on_empty_store() -> None:
    lifecycle, _ = _lifecycle()
    text = lifecycle.on_post_compact()
    assert text.splitlines()[0] == HEADING_POST_COMPACT
    assert f"{HEADING_CHECKPOINT}\nNo checkpoint found. Use retain(checkpoint=true) before next compaction." in text
    assert f"{HEADING_CONTEXT}\nNo prior memories found." in text
    assert text.endswith("---\nUse recall() / get(ref_id) for full content of any memory shown above.")


def test_post_compact_reinjects_checkpoint_context_and_candidates_without_purging() -> None:
    lifecycle, svc = _lifecycle()
    svc.retain("Use Postgres", MemoryType.DECISION)
    obs = svc.retain("flaky test on CI", MemoryType.OBSERVATION)
    lifecycle.on_pre_compact("Current: wiring the service")
    text = lifecycle.on_post_compact()
    assert "Current: wiring the service" in text
    assert "- [decision] Use Postgres" in text
    assert f"- {obs} [observation, recalled 0x]: flaky test on CI" in text
    assert svc.get(obs, touch=False) is not None


def test_session_end_retains_summary_and_lists_candidates() -> None:
    lifecycle, svc = _lifecycle()
    obs = svc.retain("learned the build command", MemoryType.OBSERVATION)
    text = lifecycle.on_session_end("Done: all phases")
    assert text.splitlines()[0] == HEADING_SESSION_END
    assert "Session summary retained as checkpoint — ref_id=" in text
    assert f"- {obs} [observation" in text
    assert text.endswith("---\nPurged 0 expired short-term memories.")
    checkpoints = svc.recall("Done: all phases", checkpoint_only=True, touch=False)
    memory = svc.get(checkpoints[0].ref_id, touch=False)
    assert memory is not None and memory.tags == ["checkpoint", "session-end"]


def test_session_end_without_summary_only_consolidates() -> None:
    lifecycle, svc = _lifecycle()
    text = lifecycle.on_session_end("   ")
    assert "No session summary retained." in text
    assert svc.count() == 0


def test_settings_default_to_environment_when_omitted() -> None:
    settings = _settings()
    svc = build_service(settings, embedding=MockEmbedding(), chroma_client=chromadb.EphemeralClient())
    assert isinstance(MemoryLifecycle(svc)._settings, MemKernelSettings)  # noqa: SLF001


# ── memkernel-0-6-compaction-hooks (#68): source branching and compact_summary ─


def _spy(monkeypatch: pytest.MonkeyPatch, svc: Any, *names: str) -> dict[str, int]:
    calls = dict.fromkeys(names, 0)
    for name in names:
        real = getattr(svc, name)

        def counted(*args: Any, _name: str = name, _real: Any = real, **kwargs: Any) -> Any:
            calls[_name] += 1
            return _real(*args, **kwargs)

        monkeypatch.setattr(svc, name, counted)
    return calls


def test_an_agent_checkpoint_survives_a_compaction_without_a_summary() -> None:
    """SC-1: the next start still shows the agent's own checkpoint."""
    lifecycle, svc = _lifecycle()
    svc.retain("SESSION CHECKPOINT agent\n\nNext: wire the store", MemoryType.EPISODE, checkpoint=True)
    lifecycle.on_pre_compact("")

    assert "Next: wire the store" in lifecycle.on_session_start("startup")


def test_capture_compact_summary_retains_a_tagged_checkpoint_shown_at_the_next_start() -> None:
    """SC-2: Claude Code's summary becomes the newest checkpoint, tagged, for the next session."""
    lifecycle, svc = _lifecycle()
    svc.retain("SESSION CHECKPOINT agent\n\nNext: older", MemoryType.EPISODE, checkpoint=True)
    status = lifecycle.capture_compact_summary("Summary: the store lock landed", session_id="s-1", trigger="auto")

    assert status.startswith("MemKernel: compaction summary (auto) retained as a checkpoint — ref_id=")
    memory = svc.get(status.split("ref_id=")[1], touch=False)
    assert memory is not None and memory.checkpoint and memory.type == MemoryType.EPISODE
    assert memory.tags == ["checkpoint", "compact-summary", "session:s-1"]
    assert "Summary: the store lock landed" in lifecycle.on_session_start("startup")
    assert lifecycle.capture_compact_summary("") == "MemKernel: the compaction carried no summary; nothing retained"


@pytest.mark.parametrize("source", ["resume", "fork"])
def test_resume_and_fork_print_nothing_and_touch_nothing(monkeypatch: pytest.MonkeyPatch, source: str) -> None:
    """SC-3: the context already holds what memkernel would add."""
    lifecycle, svc = _lifecycle()
    calls = _spy(monkeypatch, svc, "consolidate", "recall")

    assert lifecycle.on_session_start(source) == ""
    assert calls == {"consolidate": 0, "recall": 0}


@pytest.mark.parametrize("post_compact_first", [True, False])
def test_the_compact_block_shows_the_agents_checkpoint_never_the_summary_in_either_hook_order(
    monkeypatch: pytest.MonkeyPatch, post_compact_first: bool
) -> None:
    """SC-4: the same block whichever of PostCompact and SessionStart(compact) runs first; no consolidation."""
    lifecycle, svc = _lifecycle()
    svc.retain("Use Postgres", MemoryType.DECISION)
    svc.retain("SESSION CHECKPOINT agent\n\nNext: wire the store", MemoryType.EPISODE, checkpoint=True)
    if post_compact_first:
        lifecycle.capture_compact_summary("Summary: CLAUDE-SUMMARY-TEXT", session_id="s-1")
    calls = _spy(monkeypatch, svc, "consolidate")

    text = lifecycle.on_session_start("compact")

    if not post_compact_first:
        lifecycle.capture_compact_summary("Summary: CLAUDE-SUMMARY-TEXT", session_id="s-1")
    assert text.splitlines()[0] == HEADING_POST_COMPACT
    assert "Next: wire the store" in text and "CLAUDE-SUMMARY-TEXT" not in text
    assert "- [decision] Use Postgres" in text and HEADING_CANDIDATES not in text
    assert "it may predate this session's work." in text
    assert calls == {"consolidate": 0}
    assert text == lifecycle.on_session_start("compact")  # the summary captured since changes nothing


def test_the_compact_block_shows_the_checkpoints_age(monkeypatch: pytest.MonkeyPatch) -> None:
    """SC-4: a checkpoint saved earlier is labelled with its age and UTC time (FR-004)."""
    from datetime import UTC, datetime, timedelta

    from memkernel import lifecycle as module

    lifecycle, svc = _lifecycle()
    ref = svc.retain("SESSION CHECKPOINT agent\n\nNext: x", MemoryType.EPISODE, checkpoint=True)
    memory = svc.get(ref, touch=False)
    assert memory is not None
    saved = memory.timestamp.astimezone(UTC)

    class ThreeHoursLater(datetime):
        @classmethod
        def now(cls, tz: Any = None) -> Any:
            return saved + timedelta(hours=3, minutes=5)

    monkeypatch.setattr(module, "datetime", ThreeHoursLater)
    text = lifecycle.on_session_start("compact")

    assert f"Saved 3 hours ago ({saved.strftime('%Y-%m-%d %H:%M UTC')}); it may predate this session's work." in text


@pytest.mark.parametrize(
    ("minutes", "expected"),
    [(0, "0 minutes"), (1, "1 minute"), (59, "59 minutes"), (60, "1 hour"), (47 * 60, "47 hours"), (48 * 60, "2 days")],
)
def test_age_units(minutes: int, expected: str) -> None:
    from datetime import timedelta

    from memkernel.lifecycle import _age

    assert _age(timedelta(minutes=minutes)) == expected


def test_compact_without_any_own_checkpoint_says_so() -> None:
    lifecycle, _ = _lifecycle()
    lifecycle.capture_compact_summary("Summary: only Claude's", session_id="s-1")

    text = lifecycle.on_session_start("compact")

    assert f"{HEADING_CHECKPOINT}\nNo checkpoint found." in text and "only Claude's" not in text


@pytest.mark.parametrize("source", [None, "startup", "clear", "something-new"])
def test_startup_clear_no_source_and_unknown_values_give_the_full_block(source: str | None) -> None:
    """SC-5: today's block and headings; clear is intended to get it (FR-003)."""
    lifecycle, _ = _lifecycle()
    text = lifecycle.on_session_start(source)
    assert text.splitlines()[0] == HEADING_SESSION_START
    assert text.endswith("---\nPurged 0 expired short-term memories. Use recall() / get(ref_id) for details.")

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

    stamp = saved.strftime("%Y-%m-%d %H:%M UTC")
    assert f"Saved 3 hours ago ({stamp}, {ref}); it may predate this session's work." in text  # FR-001: the ref_id


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


OLD_RECALL_WINDOW = 200  # checkpoints were once picked from this many relevance-ranked recall hits


def _many_matching_checkpoints(svc: Any, count: int, tags: list[str] | None = None) -> None:
    for i in range(count):
        svc.retain(
            f"SESSION CHECKPOINT {i}\n\nsession checkpoint decisions conventions next steps {i}",
            MemoryType.EPISODE,
            checkpoint=True,
            tags=tags,
        )


@pytest.mark.parametrize("source", ["compact", "startup"])
def test_the_newest_checkpoint_is_found_beyond_the_relevance_window(source: str) -> None:
    """Review of #73: more older checkpoints than the old recall window (200) match its query better than the newest;
    the newest is still the one shown (FR-004 for compact; the startup block has the same rule)."""
    lifecycle, svc = _lifecycle()
    _many_matching_checkpoints(svc, OLD_RECALL_WINDOW + 5)
    svc.retain("zz NEWEST-UNRELATED", MemoryType.EPISODE, checkpoint=True)

    assert "NEWEST-UNRELATED" in lifecycle.on_session_start(source)


def test_an_agent_checkpoint_behind_many_compact_summaries_is_still_found() -> None:
    """Review of #73: a recall window filled with compact-summary checkpoints must not hide the agent's own."""
    from memkernel.lifecycle import COMPACT_SUMMARY_TAG

    lifecycle, svc = _lifecycle()
    svc.retain("zz AGENT-OWN", MemoryType.EPISODE, checkpoint=True)
    _many_matching_checkpoints(svc, OLD_RECALL_WINDOW + 5, tags=["checkpoint", COMPACT_SUMMARY_TAG])

    text = lifecycle.on_session_start("compact")

    assert "AGENT-OWN" in text and "No checkpoint found." not in text


@pytest.mark.parametrize("source", ["compact", "startup"])
def test_an_expired_checkpoint_is_not_shown(source: str) -> None:
    """Live as recall defined it: an episode past its retention window is not the latest checkpoint."""
    from datetime import UTC, datetime, timedelta

    lifecycle, svc = _lifecycle(episode_ttl_days=30)
    ref = svc.retain("SESSION CHECKPOINT long ago\n\nNext: EXPIRED-ONE", MemoryType.EPISODE, checkpoint=True)
    svc._vector_store.update_metadata(ref, {"timestamp": (datetime.now(UTC) - timedelta(days=60)).isoformat()})

    text = lifecycle.on_session_start(source)

    assert "EXPIRED-ONE" not in text and "No checkpoint found" in text


@pytest.mark.parametrize("call", ["startup", "compact", "post_compact"])
def test_the_checkpoint_is_chosen_without_a_relevance_window(monkeypatch: pytest.MonkeyPatch, call: str) -> None:
    """Review of #73: no path picks "the latest checkpoint" through recall(checkpoint_only=True), whose top_k
    window is ranked by relevance; every path shows the newest live checkpoint."""
    lifecycle, svc = _lifecycle()
    svc.retain("SESSION CHECKPOINT older\n\nNext: OLDER", MemoryType.EPISODE, checkpoint=True)
    svc.retain("SESSION CHECKPOINT newer\n\nNext: NEWER", MemoryType.EPISODE, checkpoint=True)
    real = svc.recall

    def recall(*args: Any, **kwargs: Any) -> Any:
        assert not kwargs.get("checkpoint_only"), "checkpoint chosen from a relevance-ranked recall window"
        return real(*args, **kwargs)

    monkeypatch.setattr(svc, "recall", recall)
    text = lifecycle.on_post_compact() if call == "post_compact" else lifecycle.on_session_start(call)

    assert "NEWER" in text and "OLDER" not in text


@pytest.mark.parametrize("call", ["compact", "post_compact"])
def test_expiry_is_judged_with_the_services_settings(call: str) -> None:
    """Review of #73: a harness passing settings only to build_service; the lifecycle's default TTL (30 days) must
    not hide a checkpoint the service (90 days) still keeps."""
    from datetime import UTC, datetime, timedelta

    settings = _settings(episode_ttl_days=90)
    svc = build_service(settings, embedding=MockEmbedding(), chroma_client=chromadb.EphemeralClient())
    lifecycle = MemoryLifecycle(svc)
    ref = svc.retain("SESSION CHECKPOINT\n\nNext: FORTY-FIVE-DAYS", MemoryType.EPISODE, checkpoint=True)
    svc._vector_store.update_metadata(ref, {"timestamp": (datetime.now(UTC) - timedelta(days=45)).isoformat()})

    text = lifecycle.on_post_compact() if call == "post_compact" else lifecycle.on_session_start(call)

    assert "FORTY-FIVE-DAYS" in text


# ── memkernel-0-7-hooks phase 1: D5–D8 and the agents' latest checkpoint ──────


def _memory_lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.startswith("- [")]


@pytest.mark.parametrize("source", ["startup", "compact"])
def test_every_injected_memory_line_and_the_checkpoint_carry_a_ref_id(source: str) -> None:
    """SC-1 (D5)."""
    lifecycle, svc = _lifecycle()
    refs = {svc.retain(f"Decision {i}: use tool {i}", MemoryType.DECISION) for i in range(3)}
    checkpoint = svc.retain("SESSION CHECKPOINT\n\nNext: wire tool 1", MemoryType.EPISODE, checkpoint=True)

    text = lifecycle.on_session_start(source)

    lines = _memory_lines(text)
    assert lines and all(line.endswith(")") and line.rsplit("(", 1)[1][:-1] in refs for line in lines)
    assert f", {checkpoint}); it may predate" in text
    for line in lines:
        assert svc.get(line.rsplit("(", 1)[1][:-1], touch=False) is not None


def test_startup_context_is_chosen_by_type_importance_and_recency_without_touching() -> None:
    """SC-2 (D6, H1): no query; decisions before conventions before facts; injecting changes no access count."""
    lifecycle, svc = _lifecycle()
    fact = svc.retain("The CI runner has 4 cores", MemoryType.FACT)
    convention = svc.retain("Branch names start with feature/", MemoryType.CONVENTION)
    decision = svc.retain("Use Postgres for the user DB", MemoryType.DECISION)

    text = lifecycle.on_session_start("startup")

    order = [line.rsplit("(", 1)[1][:-1] for line in _memory_lines(text)]
    assert order[:3] == [decision, convention, fact]
    assert all(m.access_count == 0 for m in svc.list_memories() if m.ref_id in {fact, convention, decision})


def test_the_compact_block_recalls_context_with_the_checkpoint_text() -> None:
    """SC-2 (H1): the work in progress is the query."""
    lifecycle, svc = _lifecycle()
    for i in range(8):
        svc.retain(f"Unrelated decision number {i} about logging format", MemoryType.DECISION)
    target = svc.retain("Use arq for background jobs because it is async-native", MemoryType.DECISION)
    svc.retain("SESSION CHECKPOINT\n\nCurrent: moving background jobs to arq", MemoryType.EPISODE, checkpoint=True)

    text = lifecycle.on_session_start("compact")

    assert target in text
    assert svc.get(target, touch=False).access_count == 0  # type: ignore[union-attr]


def test_each_block_stays_under_the_budget_and_names_what_to_get(monkeypatch: pytest.MonkeyPatch) -> None:
    """SC-3 (D7): an oversized checkpoint, 50 flagged memories and long candidates still fit under 9,000."""
    from memkernel import lifecycle as module

    lifecycle, svc = _lifecycle()
    big = svc.retain(
        "SESSION CHECKPOINT\n\n" + "\n".join(f"line {i} " + "x" * 80 for i in range(200)),
        MemoryType.EPISODE,
        checkpoint=True,
    )
    for i in range(30):
        svc.retain(f"Decision {i}: " + "y" * 300, MemoryType.DECISION)
    real = svc.consolidate

    def flooded(*args: Any, **kwargs: Any) -> Any:
        report = real(*args, **kwargs)
        report["candidates"] = [
            {"ref_id": f"c{i}", "type": "observation", "access_count": 1, "preview": "z" * 190} for i in range(50)
        ]
        report["revalidated"] = {
            "flagged": [{"source": f"src/f{i}.py", "reason": "changed", "ref_id": f"r{i}"} for i in range(50)]
        }
        return report

    monkeypatch.setattr(svc, "consolidate", flooded)
    for source in ("startup", "compact"):
        text = lifecycle.on_session_start(source)
        assert len(text) < module.TOTAL_BUDGET, (source, len(text))
        assert f"(truncated; get({big}) for the rest)" in text
    startup = lifecycle.on_session_start("startup")
    assert "… and 40 more (consolidate(revalidate=true) lists all)" in startup


def test_an_item_equal_to_the_checkpoint_or_a_shown_promotions_source_appears_once() -> None:
    """SC-4 (D8): de-duplication inside one block."""
    from memkernel.lifecycle import _distinct

    lifecycle, svc = _lifecycle()
    a = svc.retain("Use Postgres", MemoryType.DECISION)
    twin = svc.retain("Use Postgres", MemoryType.FACT)  # same content, another record
    source = svc.retain("Deploys go out on Tuesdays", MemoryType.CONVENTION)
    promoted = svc.retain("Deploys go out on Tuesdays, never Fridays", MemoryType.CONVENTION, promoted_from=source)
    memories = [svc.get(r, touch=False) for r in (a, twin, source, promoted)]
    assert all(m is not None for m in memories)

    kept = _distinct([m for m in memories if m is not None], None, 10)

    assert [m.ref_id for m in kept] == [a, promoted]
    checkpoint = svc.get(a, touch=False)
    assert [m.ref_id for m in _distinct([m for m in memories if m is not None], checkpoint, 10)] == [promoted]

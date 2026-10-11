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


def test_pre_compact_without_summary_uses_placeholder() -> None:
    lifecycle, svc = _lifecycle()
    status = lifecycle.on_pre_compact("")
    ref_id = status.split("ref_id=")[1].split(";")[0]
    memory = svc.get(ref_id, touch=False)
    assert memory is not None and memory.content.endswith("Compaction triggered — no summary provided.")


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

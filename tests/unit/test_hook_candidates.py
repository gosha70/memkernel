# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""on_post_compact queries by the latest checkpoint and collapses chains like the other hook paths
(memkernel-0-11-anti-rot-injection FR-002, FR-004, A5; SC-2, SC-6)."""

from __future__ import annotations

import uuid
from typing import Any

import chromadb
import pytest

from memkernel.config import MemKernelSettings
from memkernel.core.models import MemoryTier, MemoryType
from memkernel.factory import build_service
from memkernel.lifecycle import HOOK_CANDIDATES, POST_COMPACT_FIXED_QUERY, MemoryLifecycle
from tests.conftest import MockEmbedding

pytestmark = pytest.mark.unit

CHECKPOINT = "SESSION CHECKPOINT\nCurrent: migrate the user store to Postgres.\nNext: run the migration tests."


def _lifecycle() -> tuple[MemoryLifecycle, Any]:
    settings = MemKernelSettings(project_id=f"hc-{uuid.uuid4().hex[:8]}", chroma_persist_path="")
    svc = build_service(settings, embedding=MockEmbedding(), chroma_client=chromadb.EphemeralClient())
    return MemoryLifecycle(svc, settings), svc


def _record_recalls(svc: Any, monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    real = svc.recall

    def spy(query: str, **kwargs: Any) -> Any:
        calls.append({"query": query, **kwargs})
        return real(query, **kwargs)

    monkeypatch.setattr(svc, "recall", spy)
    return calls


def test_post_compact_queries_by_the_latest_checkpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    lifecycle, svc = _lifecycle()
    svc.retain("Use Postgres for the user store.", MemoryType.DECISION)
    svc.retain(CHECKPOINT, MemoryType.EPISODE, checkpoint=True)
    calls = _record_recalls(svc, monkeypatch)
    lifecycle.on_post_compact()
    (call,) = calls
    assert call["query"] == CHECKPOINT and call["query"] != POST_COMPACT_FIXED_QUERY
    assert call["top_k"] == HOOK_CANDIDATES and call["tier"] == MemoryTier.LONG_TERM


def test_post_compact_without_a_checkpoint_keeps_the_fixed_query(monkeypatch: pytest.MonkeyPatch) -> None:
    lifecycle, svc = _lifecycle()
    svc.retain("Use Postgres for the user store.", MemoryType.DECISION)
    calls = _record_recalls(svc, monkeypatch)
    lifecycle.on_post_compact()
    assert [c["query"] for c in calls] == [POST_COMPACT_FIXED_QUERY] and calls[0]["top_k"] == HOOK_CANDIDATES


def test_compact_recovery_fetches_the_same_window(monkeypatch: pytest.MonkeyPatch) -> None:
    lifecycle, svc = _lifecycle()
    svc.retain(CHECKPOINT, MemoryType.EPISODE, checkpoint=True)
    calls = _record_recalls(svc, monkeypatch)
    lifecycle.on_session_start("compact")
    assert [(c["query"], c["top_k"]) for c in calls] == [(CHECKPOINT, HOOK_CANDIDATES)]


@pytest.mark.parametrize("path", ["startup", "compact", "post-compact"])
def test_a_promoted_memory_and_its_source_never_both_appear(path: str) -> None:
    lifecycle, svc = _lifecycle()
    # Both long-term, so both can be in a recall window (the hook paths search the long-term tier only).
    source = svc.retain("migrate the user store to Postgres: the schema fact", MemoryType.FACT)
    promoted = svc.promote(source, MemoryType.DECISION, content="migrate the user store to Postgres: decided")
    svc.retain(CHECKPOINT, MemoryType.EPISODE, checkpoint=True)
    text = lifecycle.on_post_compact() if path == "post-compact" else lifecycle.on_session_start(path)
    assert promoted in text and source not in text, path

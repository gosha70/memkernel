# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""Receipts and correlation (memkernel-0-15-harness-foundations H1: FR-002, FR-003, A2–A5, A7, A8)."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import chromadb
import pytest

from memkernel import config, recall_log
from memkernel.config import RECALL_LOG_MIN_BYTES, MemKernelSettings
from memkernel.core.models import (
    EXCLUSION_REASONS,
    ID_MAX_CHARS,
    NEEDS_REVIEW_KEY,
    REVIEW_REASON_KEY,
    RUN_ID_KEY,
    Memory,
    MemoryType,
    RecallReceipt,
)
from memkernel.factory import build_service
from memkernel.lifecycle import MemoryLifecycle
from memkernel.memory.dedup import CONTENT_HASH_SCHEME, compute_content_hash
from tests.conftest import MockEmbedding

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit


def _settings(tmp_path: Path, **overrides: Any) -> MemKernelSettings:
    base: dict[str, Any] = {
        "project_id": f"h1-{uuid.uuid4().hex[:8]}",
        "chroma_persist_path": str(tmp_path / "chroma"),
        "state_dir": str(tmp_path / "state"),
        "recall_log": True,
    }
    base.update(overrides)
    return MemKernelSettings(**base)


def _service(settings: MemKernelSettings) -> Any:
    return build_service(settings, embedding=MockEmbedding(), chroma_client=chromadb.EphemeralClient())


def _records(settings: MemKernelSettings) -> list[dict[str, Any]]:
    path = recall_log.log_path(settings)
    assert path is not None
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _memory(index: int, **overrides: Any) -> Memory:
    base: dict[str, Any] = {
        "ref_id": f"ref-{index:032d}",
        "content": "x",
        "type": MemoryType.FACT,
        "project_id": "p",
        "session_id": "s",
        "timestamp": datetime.now(UTC),
        "content_hash": "h" * 64,
        "token_count": 1,
        "source": "docs/" + "s" * 40,
    }
    base.update(overrides)
    return Memory(**base)


# --- run_id on records (A2) and the id limit (A7) ---------------------------------------------------------------


def test_a_new_record_keeps_the_calls_run_id_or_the_processes(tmp_path: Path) -> None:
    svc = _service(_settings(tmp_path, run_id="run-env"))
    from_call = svc.retain("Deploys go out on Tuesdays.", MemoryType.DECISION, run_id="run-call")
    from_process = svc.retain("Releases are tagged on main.", MemoryType.DECISION)
    assert svc.get(from_call, touch=False).run_id == "run-call"
    assert svc.get(from_process, touch=False).run_id == "run-env"


def test_a_dedup_hit_keeps_the_run_that_created_the_record(tmp_path: Path) -> None:
    svc = _service(_settings(tmp_path))
    first = svc.retain("Deploys go out on Tuesdays.", MemoryType.DECISION, run_id="run-1")
    again = svc.retain("Deploys go out on Tuesdays.", MemoryType.DECISION, run_id="run-2")
    assert again == first and svc.get(first, touch=False).run_id == "run-1"


def test_a_record_without_a_run_loads_with_an_empty_one(tmp_path: Path) -> None:
    """SC-4: a record written without the key, as by an older memkernel, loads with the default."""
    svc = _service(_settings(tmp_path))
    ref = svc.retain("Deploys go out on Tuesdays.", MemoryType.DECISION)
    stored = svc._vector_store._collection.get(ids=[ref], include=["metadatas"])["metadatas"][0]
    assert RUN_ID_KEY not in stored and svc.get(ref, touch=False).run_id == ""


def test_an_over_long_run_id_is_refused_at_retain(tmp_path: Path) -> None:
    svc = _service(_settings(tmp_path))
    with pytest.raises(ValueError, match=f"run_id is {ID_MAX_CHARS + 1} characters; the limit is {ID_MAX_CHARS}"):
        svc.retain("Deploys go out on Tuesdays.", MemoryType.DECISION, run_id="r" * (ID_MAX_CHARS + 1))
    svc.retain("Exactly at the limit.", MemoryType.DECISION, run_id="r" * ID_MAX_CHARS)


def test_an_over_long_id_setting_is_ignored_with_one_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(config, "_warned_ids", set())
    monkeypatch.setenv("MEMKERNEL_AGENT_ID", "a" * (ID_MAX_CHARS + 1))
    with caplog.at_level(logging.WARNING, logger="memkernel.config"):
        first, second = _settings(tmp_path), _settings(tmp_path)
    assert first.agent_id == "" and second.agent_id == ""
    warnings = [r for r in caplog.records if "MEMKERNEL_AGENT_ID" in r.getMessage()]
    assert len(warnings) == 1 and "is ignored" in warnings[0].getMessage()


# --- the receipt (A3, A4) ---------------------------------------------------------------------------------------


def test_a_recall_receipt_counts_each_exclusion_and_lists_what_it_returned(tmp_path: Path) -> None:
    svc = _service(_settings(tmp_path, observation_ttl_days=7))
    old = svc.retain("The user store runs on MySQL.", MemoryType.DECISION)
    svc.retain("The user store runs on Postgres.", MemoryType.DECISION, supersedes=old)
    flagged = svc.retain("The user store schema lives in schema.sql.", MemoryType.FACT)
    svc._vector_store.update_metadata(flagged, {NEEDS_REVIEW_KEY: True, REVIEW_REASON_KEY: "changed"})
    expired = svc.retain("The user store was slow on Monday.", MemoryType.OBSERVATION)
    svc._vector_store.update_metadata(expired, {"timestamp": (datetime.now(UTC) - timedelta(days=60)).isoformat()})
    svc.retain("The user store is backed up nightly.", MemoryType.CONVENTION)

    receipt = RecallReceipt()
    results = svc.recall("user store", top_k=10, receipt=receipt)

    assert receipt.excluded == {"superseded": 1, "flagged": 1, "expired": 1}
    assert [m.ref_id for m in receipt.memories] == [r.ref_id for r in results]
    assert {old, flagged, expired}.isdisjoint(r.ref_id for r in results)


def test_exclusions_are_the_last_windows_not_a_sum_over_windows(tmp_path: Path) -> None:
    """A4: three flagged candidates and nothing live; top_k=1 searches a window of 2, then of 4 (the store runs out).
    The last window dropped 3; a sum over windows would say 5."""
    svc = _service(_settings(tmp_path))
    for text in ("The user store runs on Postgres.", "The user store has a replica.", "The user store is sharded."):
        ref = svc.retain(text, MemoryType.FACT)
        svc._vector_store.update_metadata(ref, {NEEDS_REVIEW_KEY: True, REVIEW_REASON_KEY: "changed"})
    receipt = RecallReceipt()
    assert svc.recall("user store", top_k=1, receipt=receipt) == []
    assert receipt.excluded == {"superseded": 0, "flagged": 3, "expired": 0} and receipt.memories == []


def test_a_recall_without_a_receipt_returns_the_same_list(tmp_path: Path) -> None:
    svc = _service(_settings(tmp_path))
    for text in ("The user store runs on Postgres.", "The user store is backed up nightly."):
        svc.retain(text, MemoryType.DECISION)
    plain = svc.recall("user store", top_k=5, touch=False)
    with_receipt = svc.recall("user store", top_k=5, touch=False, receipt=RecallReceipt())
    assert [r.ref_id for r in plain] == [r.ref_id for r in with_receipt]


def test_a_newest_recall_receipt_lists_the_checkpoints_and_no_exclusions(tmp_path: Path) -> None:
    svc = _service(_settings(tmp_path))
    checkpoint = svc.retain("SESSION CHECKPOINT\nDone: schema.", MemoryType.EPISODE, checkpoint=True)
    receipt = RecallReceipt(excluded={"superseded": 9})
    svc.recall("session checkpoint", checkpoint_only=True, order="newest", top_k=1, receipt=receipt)
    assert [m.ref_id for m in receipt.memories] == [checkpoint] and receipt.excluded is None


def test_a_receipt_entry_keeps_hashes_and_state_never_content() -> None:
    flagged = recall_log.receipt_entry(
        _memory(1, content="secret body", source="src/app.py", source_hash="abc", needs_review=True)
    )
    assert flagged == {
        "ref_id": _memory(1).ref_id,
        "content_hash": "h" * 64,
        "content_hash_scheme": CONTENT_HASH_SCHEME,
        "source": "src/app.py",
        "source_hash": "abc",
        "state": "flagged",
    }
    plain = recall_log.receipt_entry(_memory(2, source=""))
    assert plain["state"] == "live" and "source" not in plain and "source_hash" not in plain
    assert CONTENT_HASH_SCHEME == "sha256-raw" and compute_content_hash("a") == compute_content_hash("a")


# --- the record (FR-002, FR-003, A5) ----------------------------------------------------------------------------


def test_a_record_carries_the_process_ids_unless_the_call_names_its_own(tmp_path: Path) -> None:
    settings = _settings(tmp_path, run_id="run-env", agent_id="agent-env", task_id="task-env")
    recall_log.append(settings, recall_log.ORIGIN_TOOL, [], query="a")
    recall_log.append(settings, recall_log.ORIGIN_TOOL, [], query="b", ids=recall_log.Correlation("run-call"))
    first, second = _records(settings)
    assert (first["run_id"], first["agent_id"], first["task_id"]) == ("run-env", "agent-env", "task-env")
    assert (second["run_id"], second["agent_id"], second["task_id"]) == ("run-call", "", "")
    assert first["memories"] == [] and first["returned_chars"] == 0
    assert "latency_ms" not in first and "excluded" not in first


def test_a_long_query_is_cut_before_any_detail(tmp_path: Path) -> None:
    settings = _settings(tmp_path, recall_log_max_bytes=RECALL_LOG_MIN_BYTES)
    memories = [_memory(i) for i in range(10)]
    recall_log.append(settings, "tool", [m.ref_id for m in memories], query="q" * 2_000, memories=memories)
    (record,) = _records(settings)
    assert 0 < len(record["query"]) < 2_000 and len(record["memories"]) == 10 and len(record["ref_ids"]) == 10
    assert record["truncated"] is True and "memories_truncated" not in record and "ref_ids_truncated" not in record


def test_details_are_cut_before_ref_ids(tmp_path: Path) -> None:
    settings = _settings(tmp_path, recall_log_max_bytes=RECALL_LOG_MIN_BYTES)
    memories = [_memory(i) for i in range(40)]
    recall_log.append(settings, "tool", [m.ref_id for m in memories], query="q" * 500, memories=memories)
    (record,) = _records(settings)
    assert record["query"] == "" and 0 < len(record["memories"]) < 40 and len(record["ref_ids"]) == 40
    assert record["memories"] == [recall_log.receipt_entry(m) for m in memories[: len(record["memories"])]]
    assert record["memories_truncated"] is True and "ref_ids_truncated" not in record


def test_ref_ids_go_last(tmp_path: Path) -> None:
    settings = _settings(tmp_path, recall_log_max_bytes=RECALL_LOG_MIN_BYTES)
    memories = [_memory(i) for i in range(200)]
    recall_log.append(settings, "tool", [m.ref_id for m in memories], query="q", memories=memories)
    (record,) = _records(settings)
    assert record["memories"] == [] and 0 < len(record["ref_ids"]) < 200
    assert record["memories_truncated"] is True and record["ref_ids_truncated"] is True


def test_the_size_floor_holds_a_full_receipt_with_ids_at_their_limit(tmp_path: Path) -> None:
    settings = _settings(tmp_path, recall_log_max_bytes=RECALL_LOG_MIN_BYTES)
    longest = recall_log.Correlation("r" * ID_MAX_CHARS, "a" * ID_MAX_CHARS, "t" * ID_MAX_CHARS)
    filters = {"type": "decision", "tier": "long_term", "session_id_filter": "s" * 40, "top_k": 5, "order": "relevance"}
    recall_log.append(
        settings,
        "tool",
        ["a" * 36],
        query="q" * 2_000,
        filters=filters,
        ids=longest,
        memories=[_memory(1)],
        returned_chars=200,
        latency_ms=12.5,
        excluded=dict.fromkeys(EXCLUSION_REASONS, 3),
    )
    (record,) = _records(settings)
    assert record["run_id"] == longest.run_id and record["ref_ids"] == ["a" * 36] and len(record["memories"]) == 1
    assert record["excluded"] == dict.fromkeys(EXCLUSION_REASONS, 3) and record["latency_ms"] == 12.5


def test_a_hook_record_lists_what_the_block_showed_with_the_process_ids(tmp_path: Path) -> None:
    settings = _settings(tmp_path, run_id="run-9", agent_id="planner")
    svc = _service(settings)
    decision = svc.retain("Use Postgres for the user store.", MemoryType.DECISION)
    text = MemoryLifecycle(svc, settings).on_session_start("startup", session_id="s1")
    (record,) = _records(settings)
    assert decision in record["ref_ids"] and [m["ref_id"] for m in record["memories"]] == record["ref_ids"]
    assert record["returned_chars"] == len(text) and (record["run_id"], record["agent_id"]) == ("run-9", "planner")
    assert "latency_ms" not in record and "excluded" not in record

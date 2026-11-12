# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""The recall log (memkernel-0-10-recall-log SC-1, SC-2; FR-001 to FR-004, A1)."""

from __future__ import annotations

import json
import logging
import stat
import uuid
from typing import TYPE_CHECKING, Any

import chromadb
import pytest

from memkernel import recall_log
from memkernel.config import MemKernelSettings
from memkernel.core.models import MemoryType
from memkernel.factory import build_service
from memkernel.lifecycle import BLOCK_COMPACT_RECOVERY, BLOCK_SESSION_START, MemoryLifecycle
from tests.conftest import MockEmbedding

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit


def _settings(tmp_path: Path, **overrides: Any) -> MemKernelSettings:
    base: dict[str, Any] = {
        "project_id": f"rl-{uuid.uuid4().hex[:8]}",
        "chroma_persist_path": str(tmp_path / "chroma"),
        "state_dir": str(tmp_path / "state"),
        "recall_log": True,
    }
    base.update(overrides)
    return MemKernelSettings(**base)


def _records(settings: MemKernelSettings) -> list[dict[str, Any]]:
    path = recall_log.log_path(settings)
    assert path is not None
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _log_files(path: Path) -> list[Path]:
    """The log and its rotated files; the lock file is not one of them."""
    return sorted(f for f in path.parent.glob(f"{path.name}*") if not f.name.endswith(".lock"))


def _lifecycle(settings: MemKernelSettings) -> tuple[MemoryLifecycle, Any]:
    svc = build_service(settings, embedding=MockEmbedding(), chroma_client=chromadb.EphemeralClient())
    return MemoryLifecycle(svc, settings), svc


@pytest.fixture(autouse=True)
def _fresh_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(recall_log, "_warned", False)


def test_one_record_with_every_field(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    recall_log.append(settings, recall_log.ORIGIN_TOOL, ["a", "b"], query="db choice", filters={"top_k": 3})
    (record,) = _records(settings)
    assert record["origin"] == "tool" and record["ref_ids"] == ["a", "b"] and record["query"] == "db choice"
    assert record["filters"] == {"top_k": 3} and record["session_id"] == "" and "block" not in record
    assert record["time"].endswith("+00:00")


def test_the_file_is_private_and_the_query_is_capped(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    recall_log.append(settings, recall_log.ORIGIN_TOOL, [], query="q" * 5_000)
    path = recall_log.log_path(settings)
    assert path is not None and stat.S_IMODE(path.stat().st_mode) == recall_log.FILE_MODE
    assert len(_records(settings)[0]["query"]) == recall_log.QUERY_MAX_CHARS


@pytest.mark.parametrize("overrides", [{"recall_log": False}, {"chroma_persist_path": ""}], ids=["off", "in-memory"])
def test_off_or_in_memory_writes_nothing(tmp_path: Path, overrides: dict[str, Any]) -> None:
    settings = _settings(tmp_path, **overrides)
    lifecycle, svc = _lifecycle(settings)
    svc.retain("Use Postgres.", MemoryType.DECISION)
    lifecycle.on_session_start("startup", session_id="s1")
    recall_log.append(settings, recall_log.ORIGIN_TOOL, ["x"], query="q")
    assert recall_log.log_path(settings) is None
    assert not (tmp_path / "state" / recall_log.RECALL_LOG_DIR).exists()


def test_rotation_keeps_the_file_count_and_size(tmp_path: Path) -> None:
    settings = _settings(tmp_path, recall_log_max_bytes=400, recall_log_max_files=3)
    for i in range(40):
        recall_log.append(settings, recall_log.ORIGIN_TOOL, [f"r{i}"], query=f"query {i}")
    path = recall_log.log_path(settings)
    assert path is not None
    files = _log_files(path)
    assert [f.name for f in files] == ["recall.jsonl", "recall.jsonl.1", "recall.jsonl.2"]
    assert all(f.stat().st_size <= 400 for f in files)
    assert _records(settings)[-1]["ref_ids"] == ["r39"]  # the newest record is in the current file


def test_one_file_means_the_log_restarts(tmp_path: Path) -> None:
    settings = _settings(tmp_path, recall_log_max_bytes=200, recall_log_max_files=1)
    for i in range(10):
        recall_log.append(settings, recall_log.ORIGIN_TOOL, [f"r{i}"])
    path = recall_log.log_path(settings)
    assert path is not None and [f.name for f in _log_files(path)] == ["recall.jsonl"]
    assert path.stat().st_size <= 200


def test_a_failed_write_is_logged_once_and_never_raises(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    (tmp_path / "state").write_text("a file where the directory should be")
    settings = _settings(tmp_path)
    with caplog.at_level(logging.WARNING, logger="memkernel.recall_log"):
        for _ in range(3):
            recall_log.append(settings, recall_log.ORIGIN_TOOL, ["x"], query="q")
    assert sum("recall log" in r.getMessage() for r in caplog.records) == 1


def test_session_start_logs_what_it_shows(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    lifecycle, svc = _lifecycle(settings)
    decision = svc.retain("Use Postgres for the user store.", MemoryType.DECISION)
    checkpoint = svc.retain("SESSION CHECKPOINT\nDone: schema.", MemoryType.EPISODE, checkpoint=True)
    text = lifecycle.on_session_start("startup", session_id="s1")
    (record,) = _records(settings)
    assert record["origin"] == "hook" and record["block"] == BLOCK_SESSION_START and record["session_id"] == "s1"
    assert record["query"] == "" and record["filters"] == {}
    assert set(record["ref_ids"]) >= {decision, checkpoint}
    assert all(ref in text for ref in record["ref_ids"])
    assert record["ref_ids"] == sorted(record["ref_ids"], key=text.index)


def test_compact_recovery_logs_with_the_session_id(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    lifecycle, svc = _lifecycle(settings)
    svc.retain("SESSION CHECKPOINT\nCurrent: the Postgres schema.", MemoryType.EPISODE, checkpoint=True)
    svc.retain("Use Postgres for the user store.", MemoryType.DECISION)
    text = lifecycle.on_session_start("compact", session_id="s2")
    (record,) = _records(settings)
    assert record["block"] == BLOCK_COMPACT_RECOVERY and record["session_id"] == "s2"
    assert record["ref_ids"] and all(ref in text for ref in record["ref_ids"])


def test_resume_shows_nothing_and_logs_nothing(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    lifecycle, svc = _lifecycle(settings)
    svc.retain("Use Postgres.", MemoryType.DECISION)
    assert lifecycle.on_session_start("resume", session_id="s3") == ""
    path = recall_log.log_path(settings)
    assert path is not None and not path.exists()

# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""A running service's recall finds records that another process wrote to its store (#139)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from memkernel.config import MemKernelSettings
from memkernel.core.models import MemoryType
from memkernel.factory import build_service
from tests.conftest import MockEmbedding

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]
WRITER = """
import sys
sys.path[:0] = [{root!r}, {src!r}]
from memkernel.config import MemKernelSettings
from memkernel.core.models import MemoryType
from memkernel.factory import build_service
from tests.conftest import MockEmbedding
settings = MemKernelSettings(project_id="xp", chroma_persist_path=sys.argv[1], state_dir=sys.argv[2])
service = build_service(settings, embedding=MockEmbedding(dimension=8))
for text in sys.argv[3:]:
    service.retain(text, MemoryType.FACT)
"""


def _settings(tmp_path: Path) -> MemKernelSettings:
    return MemKernelSettings(
        project_id="xp", chroma_persist_path=str(tmp_path / "chroma"), state_dir=str(tmp_path / "state")
    )


def _write_from_another_process(tmp_path: Path, *texts: str) -> None:
    script = WRITER.format(root=str(ROOT), src=str(ROOT / "src"))
    subprocess.run(
        [sys.executable, "-c", script, str(tmp_path / "chroma"), str(tmp_path / "state"), *texts],
        check=True,
        timeout=120,
    )


def _found(service: Any, text: str) -> bool:
    return any(service.get(r.ref_id, touch=False).content == text for r in service.recall(text, top_k=10))


def test_recall_finds_what_another_process_wrote_after_this_one_started(tmp_path: Path) -> None:
    service = build_service(_settings(tmp_path), embedding=MockEmbedding(dimension=8))
    for i in range(5):
        service.retain(f"note {i} written by the running server", MemoryType.FACT)
    assert _found(service, "note 3 written by the running server")

    _write_from_another_process(tmp_path, "zebracorn migration policy from the hook process")

    assert _found(service, "zebracorn migration policy from the hook process")  # dense and BM25 both caught up
    assert len(service._sparse_index) == 6


def test_own_writes_keep_the_seen_count_so_no_refresh_runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    service = build_service(_settings(tmp_path), embedding=MockEmbedding(dimension=8))
    refreshes: list[int] = []
    monkeypatch.setattr(service._vector_store, "refresh", lambda: refreshes.append(1))
    ref = service.retain("written here", MemoryType.FACT)
    service.retain("also written here", MemoryType.FACT)
    service.recall("written here")
    assert service._delete_record(ref)
    service.recall("written here")
    assert refreshes == []


def test_a_write_by_another_process_triggers_one_refresh(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    service = build_service(_settings(tmp_path), embedding=MockEmbedding(dimension=8))
    service.retain("written here", MemoryType.FACT)
    calls: list[int] = []
    real = service._vector_store.refresh

    def counted() -> None:
        calls.append(1)
        real()

    monkeypatch.setattr(service._vector_store, "refresh", counted)
    _write_from_another_process(tmp_path, "from elsewhere one", "from elsewhere two")
    service.recall("from elsewhere one")
    service.recall("from elsewhere two")
    assert calls == [1]

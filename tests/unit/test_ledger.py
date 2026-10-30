# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""The wiki sync ledger's key, lock and storage (memkernel-0-7 D2, FR-004)."""

from __future__ import annotations

import hashlib
import threading
import time
from typing import TYPE_CHECKING

import pytest

from memkernel.wiki.ledger import ACTION_IMPORT, STATE_APPLIED, LedgerEntry, SyncLedger, wiki_key

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit


def test_the_wiki_key_is_the_manifest_id_else_the_project_relative_path(tmp_path: Path) -> None:
    project = tmp_path / "project"
    wiki = project / "knowledge" / "wiki"
    wiki.mkdir(parents=True)

    assert wiki_key("7e50e893-20bc-41f2-8dd6-0c3b4d960da2", wiki, project) == "7e50e893-20bc-41f2-8dd6-0c3b4d960da2"
    expected = hashlib.sha256(b"knowledge/wiki").hexdigest()
    assert wiki_key(None, wiki, project) == expected
    moved = tmp_path / "elsewhere" / "project"
    (moved / "knowledge" / "wiki").mkdir(parents=True)
    assert wiki_key(None, moved / "knowledge" / "wiki", moved) == expected  # a moved project keeps its key


def test_a_persisted_ledger_round_trips_and_its_lock_serialises_runs(tmp_path: Path) -> None:
    pytest.importorskip("fcntl")
    first = SyncLedger.for_wiki(str(tmp_path / "state"), True, "p", "wiki-1", tmp_path, tmp_path)
    order: list[str] = []

    def hold() -> None:
        with first.run() as ledger:
            order.append("first in")
            ledger.mark(LedgerEntry("k", "a.md", STATE_APPLIED, ACTION_IMPORT, ref_id="r1"), STATE_APPLIED)
            time.sleep(0.4)
            order.append("first out")

    thread = threading.Thread(target=hold)
    thread.start()
    time.sleep(0.1)
    second = SyncLedger.for_wiki(str(tmp_path / "state"), True, "p", "wiki-1", tmp_path, tmp_path)
    with second.run() as ledger:
        order.append("second in")
        assert ledger.entries["k"].ref_id == "r1"  # saved by the first run before the second could load
    thread.join()

    assert order == ["first in", "first out", "second in"]


def test_an_in_memory_ledger_writes_no_file(tmp_path: Path) -> None:
    ledger = SyncLedger.for_wiki(str(tmp_path / "state"), False, "p-mem", "wiki-1", tmp_path, tmp_path)
    with ledger.run() as run:
        run.mark(LedgerEntry("k", "a.md", STATE_APPLIED, ACTION_IMPORT), STATE_APPLIED)

    assert not (tmp_path / "state").exists()
    with SyncLedger.for_wiki(str(tmp_path / "state"), False, "p-mem", "wiki-1", tmp_path, tmp_path).run() as again:
        assert "k" in again.entries  # kept for the process's life

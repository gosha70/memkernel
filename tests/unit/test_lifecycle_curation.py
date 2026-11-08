# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""The curation debt section's rendering and the in-memory ledger snapshot (memkernel-0-7-governed G2, SC-2)."""

from __future__ import annotations

import time
import uuid
from typing import TYPE_CHECKING, Any

import pytest

from memkernel.config import MemKernelSettings
from memkernel.wiki import curation
from memkernel.wiki.curation import (
    CURATION_DEBT_BUDGET,
    CURATION_HINT,
    CURATION_KIND_ORDER,
    HEADING_CURATION_DEBT,
    curation_debt_lines,
)
from memkernel.wiki.ledger import (
    _MEMORY_LEDGERS,
    STATE_APPLIED,
    STATE_FAILED,
    STATE_PENDING,
    LedgerEntry,
    LedgerUnavailableError,
    _memory_lock,
    snapshot_unfinished_in_memory,
)

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit


def _result(counts: dict[str, int], examples: list[tuple[str, str]] | None = None, **ledger: int) -> dict[str, object]:
    return {"counts": counts, "examples": examples or [], "pending": 0, "failed": 0, "key": "k", **ledger}


def test_counts_in_any_order_render_in_memkernels_order() -> None:
    order = ["unapproved", "approval-stale", "superseded-still-indexed", "stale-claim", "no-page-id"]
    shuffled = {"zz-new": 1, "no-page-id": 5, "stale-claim": 4, "aa-new": 1}
    shuffled |= {"superseded-still-indexed": 3, "approval-stale": 2, "unapproved": 1}

    rendered = curation._render(_result(shuffled, pending=1, failed=2))

    expected = [f"{kind} {shuffled[kind]}" for kind in order] + ["aa-new 1", "zz-new 1", "sync pending 1"]
    assert rendered == ["", HEADING_CURATION_DEBT, ", ".join([*expected, "sync failed 2"]), CURATION_HINT]
    assert list(CURATION_KIND_ORDER[:2]) == order[:2]


def test_the_section_stays_within_its_budget() -> None:
    long = "k" * curation.CURATION_DEBT_FIELD_CHARS
    counts = {f"{long[:-2]}{i:02d}": 1 for i in range(10)}
    examples = [("unapproved", "p" * curation.CURATION_DEBT_FIELD_CHARS)] * curation.CURATION_DEBT_MAX_LINES

    rendered = curation._render(_result(counts, examples))

    assert len("\n".join(rendered)) <= CURATION_DEBT_BUDGET and rendered[-1] == CURATION_HINT
    assert len("\n".join(curation._unavailable("r" * 2000))) <= CURATION_DEBT_BUDGET


def test_no_debt_renders_nothing() -> None:
    assert curation._render(_result({})) == []


def test_examples_put_review_kinds_first_in_order() -> None:
    findings = [("weak-orphan", "a.md"), ("approval-stale", "b.md"), ("stale-claim", "c.md"), ("unapproved", "d.md")]
    review = set(curation.CURATION_REVIEW_KINDS)
    chosen = sorted(findings, key=lambda f: (f[0] not in review, *curation._rank(f[0])))[:3]
    assert chosen == [("unapproved", "d.md"), ("approval-stale", "b.md"), ("stale-claim", "c.md")]


def test_conflict_kinds_rank_after_review_kinds_and_before_stale_claims(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    order = ["unapproved", "open-conflict", "conflict-one-sided", "conflict-dangling", "stale-claim", "no-page-id"]
    counts = {"no-page-id": 6, "conflict-dangling": 4, "stale-claim": 5, "open-conflict": 2}
    counts |= {"conflict-one-sided": 3, "unapproved": 1}
    findings = [("stale-claim", "a.md"), ("conflict-dangling", "b.md"), ("open-conflict", "c.md")]
    findings += [("unapproved", "d.md"), ("conflict-one-sided", "e.md")]
    monkeypatch.setattr(curation, "gate_available", lambda: object())
    monkeypatch.setattr(curation, "wiki_id", lambda *args: "w")
    monkeypatch.setattr(curation, "wiki_key", lambda *args: "k")
    monkeypatch.setattr(curation, "curation_findings", lambda *args: (counts, findings))

    collected = curation._collect(tmp_path, tmp_path, False, None, "p", lambda stage: None)
    rendered = curation._render(collected)

    assert rendered[2] == ", ".join(f"{kind} {counts[kind]}" for kind in order)
    assert collected["examples"] == [("unapproved", "d.md"), ("open-conflict", "c.md"), ("conflict-one-sided", "e.md")]


@pytest.mark.parametrize("over", [{"wiki_dir": ""}, {"wiki_mode": "ungated"}])
def test_no_wiki_or_ungated_starts_no_child(over: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    def never(*args: object) -> dict[str, object]:
        raise AssertionError("a child was started")

    monkeypatch.setattr(curation, "_run_child", never)
    values: dict[str, Any] = {"wiki_dir": "wiki", "chroma_persist_path": "", **over}
    settings = MemKernelSettings(**values)
    assert curation_debt_lines(settings, settings, "p") == []


def _ledger(entries: int) -> tuple[str, str]:
    project, key = f"cd-{uuid.uuid4().hex[:8]}", "k"
    states = (STATE_PENDING, STATE_FAILED, STATE_APPLIED)
    _MEMORY_LEDGERS[(project, key)] = {
        str(i): LedgerEntry(str(i), f"p{i}.md", states[i % 3], "import") for i in range(entries)
    }
    return project, key


def test_the_in_memory_snapshot_counts_unfinished_entries() -> None:
    project, key = _ledger(30)
    assert snapshot_unfinished_in_memory(project, key, time.monotonic() + 5, 100) == (10, 10)


def test_the_in_memory_snapshot_past_its_deadline_releases_the_lock() -> None:
    project, key = _ledger(250)
    with pytest.raises(LedgerUnavailableError, match="timed out"):
        snapshot_unfinished_in_memory(project, key, time.monotonic() - 1, 100)
    lock = _memory_lock((project, key))
    assert lock.acquire(blocking=False)
    lock.release()


def test_the_in_memory_snapshot_never_waits_for_an_import() -> None:
    project, key = _ledger(3)
    with _memory_lock((project, key)):
        start = time.monotonic()
        with pytest.raises(LedgerUnavailableError, match="an import holds"):
            snapshot_unfinished_in_memory(project, key, time.monotonic() + 5, 100)
        assert time.monotonic() - start < 0.5


def test_a_small_in_memory_ledger_still_honours_an_expired_deadline() -> None:
    project, key = _ledger(1)
    with pytest.raises(LedgerUnavailableError, match="timed out"):
        snapshot_unfinished_in_memory(project, key, time.monotonic() - 1, 100)

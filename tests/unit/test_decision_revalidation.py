# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""Decisions that cite files are revalidated and returned flagged (memkernel-0-10-decision-revalidation, #123)."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

import chromadb
import pytest

from memkernel.config import MemKernelSettings
from memkernel.core.models import SOURCE_HASH_KEY, MemoryType
from memkernel.factory import build_service
from memkernel.lifecycle import HEADING_NEEDS_REVIEW, MemoryLifecycle
from memkernel.memory.dedup import compute_content_hash
from tests.conftest import MockEmbedding

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit

V1 = "def redact_text(s):\n    return s.replace('secret', '***')\n"
V2 = "def redact_text(s):\n    return s\n"
DECISION = "decision: In the context of redaction, we chose redact_text over a new redactor, because one contract."


def _service(root: Path) -> tuple[Any, MemKernelSettings]:
    settings = MemKernelSettings(
        project_id=f"dr-{uuid.uuid4().hex[:8]}", chroma_persist_path="", project_root=str(root)
    )
    return build_service(settings, embedding=MockEmbedding(), chroma_client=chromadb.EphemeralClient()), settings


def _write(root: Path, rel: str, text: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _recalled(svc: Any, ref: str, **kwargs: Any) -> Any:
    return next((r for r in svc.recall("redaction redact_text contract", top_k=20, **kwargs) if r.ref_id == ref), None)


# ── SC-1 ─────────────────────────────────────────────────────────────────────


def test_the_57_probe_flags_the_decision_and_recall_still_returns_it(tmp_path: Path) -> None:
    svc, _ = _service(tmp_path)
    path = _write(tmp_path, "src/redact.py", V1)
    decision = svc.retain(DECISION, MemoryType.DECISION, source="src/redact.py")
    code = svc.retain(V1, MemoryType.CODE, source="src/redact.py")
    assert svc.get(decision).source_hash == compute_content_hash(V1)
    unflagged = _recalled(svc, decision)
    assert unflagged is not None and unflagged.needs_review is False and unflagged.review_reason == ""

    path.write_text(V2, encoding="utf-8")
    report = svc.revalidate()
    assert {(f["ref_id"], f["reason"], f["type"]) for f in report["flagged"]} == {
        (decision, "changed", "decision"),
        (code, "changed", "code"),
    }
    hit = _recalled(svc, decision)
    assert hit is not None and hit.needs_review is True and hit.review_reason == "changed"
    assert all(r.ref_id != code for r in svc.recall("redact_text secret", top_k=20))  # code stays hidden

    path.unlink()
    svc.revalidate()
    hit = _recalled(svc, decision)
    assert hit is not None and hit.review_reason == "missing"


# ── SC-2 ─────────────────────────────────────────────────────────────────────


def test_restoring_the_file_clears_the_flag(tmp_path: Path) -> None:
    svc, _ = _service(tmp_path)
    path = _write(tmp_path, "src/redact.py", V1)
    decision = svc.retain(DECISION, MemoryType.DECISION, source="src/redact.py")
    path.write_text(V2, encoding="utf-8")
    svc.revalidate()
    path.write_text(V1, encoding="utf-8")
    report = svc.revalidate()
    assert report["cleared"] == 1 and svc.get(decision).needs_review is False


def _raw_metadata(svc: Any, ref: str) -> dict[str, Any]:
    raw = svc._vector_store._collection.get(ids=[ref], include=["metadatas"])
    return dict(raw["metadatas"][0])


def test_a_pre_0_10_decision_without_the_key_is_flagged_only_when_its_file_is_missing(tmp_path: Path) -> None:
    """SC-4: a decision whose metadata has no source_hash key at all, as a 0.9.x store holds it."""
    svc, _ = _service(tmp_path)
    decision = svc.retain(DECISION, MemoryType.DECISION, source="src/redact.py")  # no file yet: no key written
    assert SOURCE_HASH_KEY not in _raw_metadata(svc, decision) and svc.get(decision).source_hash == ""
    path = _write(tmp_path, "src/redact.py", V1)
    assert svc.revalidate()["flagged"] == []
    path.write_text(V2, encoding="utf-8")
    assert svc.revalidate()["flagged"] == []  # a change cannot be told without a hash
    path.unlink()
    assert [f["reason"] for f in svc.revalidate()["flagged"]] == ["missing"]
    _write(tmp_path, "src/redact.py", V2)
    assert svc.revalidate()["cleared"] == 1
    assert SOURCE_HASH_KEY not in _raw_metadata(svc, decision)  # never hashed later


def test_an_empty_source_hash_reads_as_hashless(tmp_path: Path) -> None:
    svc, _ = _service(tmp_path)
    path = _write(tmp_path, "src/redact.py", V1)
    decision = svc.retain(DECISION, MemoryType.DECISION, source="src/redact.py")
    svc._vector_store.update_metadata(decision, {SOURCE_HASH_KEY: ""})
    path.write_text(V2, encoding="utf-8")
    assert svc.get(decision).source_hash == "" and svc.revalidate()["flagged"] == []


def test_a_hashless_decision_keeps_a_flag_its_present_file_cannot_disprove(tmp_path: Path) -> None:
    svc, _ = _service(tmp_path)
    decision = svc.retain(DECISION, MemoryType.DECISION, source="src/redact.py")  # hashless
    _write(tmp_path, "src/redact.py", V1)
    svc._set_review(decision, True, "changed")  # a flag from an earlier check
    report = svc.revalidate()
    assert report["cleared"] == 0 and report["unknown"] == 1
    assert svc.get(decision).needs_review is True and svc.get(decision).review_reason == "changed"


@pytest.mark.parametrize("source", ["../outside.py", "src/missing-at-retain.py"], ids=["outside-root", "no-file"])
def test_a_source_that_cannot_be_hashed_gets_no_hash(tmp_path: Path, source: str) -> None:
    root = tmp_path / "project"
    root.mkdir()
    (tmp_path / "outside.py").write_text(V1, encoding="utf-8")
    svc, _ = _service(root)
    decision = svc.retain(DECISION, MemoryType.DECISION, source=source)
    assert svc.get(decision).source_hash == ""
    report = svc.revalidate()
    if source.startswith(".."):
        assert report["unknown"] == 1 and report["flagged"] == []
    else:
        assert [f["reason"] for f in report["flagged"]] == ["missing"]


def test_a_decision_without_a_source_is_not_checked(tmp_path: Path) -> None:
    svc, _ = _service(tmp_path)
    svc.retain(DECISION, MemoryType.DECISION)
    assert svc.revalidate()["checked"] == 0


# ── SC-3 ─────────────────────────────────────────────────────────────────────


def test_a_dedup_hit_from_another_source_keeps_the_original_source_and_hash(tmp_path: Path) -> None:
    svc, _ = _service(tmp_path)
    _write(tmp_path, "src/a.py", V1)
    _write(tmp_path, "src/b.py", V2)
    first = svc.retain(DECISION, MemoryType.DECISION, source="src/a.py")
    again = svc.retain(DECISION, MemoryType.DECISION, source="src/b.py")
    memory = svc.get(again)
    assert again == first and memory.source == "src/a.py" and memory.source_hash == compute_content_hash(V1)


def test_a_dedup_hit_from_the_same_source_leaves_the_record_unchanged(tmp_path: Path) -> None:
    svc, _ = _service(tmp_path)
    path = _write(tmp_path, "src/a.py", V1)
    first = svc.retain(DECISION, MemoryType.DECISION, source="src/a.py")
    path.write_text(V2, encoding="utf-8")  # the file changed since; a dedup hit must not re-hash it
    again = svc.retain(DECISION, MemoryType.DECISION, source="src/a.py")
    assert again == first and svc.get(first).source_hash == compute_content_hash(V1)


def test_a_dedup_hit_on_a_hashless_record_leaves_it_hashless(tmp_path: Path) -> None:
    svc, _ = _service(tmp_path)
    _write(tmp_path, "src/a.py", V1)
    first = svc.retain(DECISION, MemoryType.DECISION, source="src/a.py")
    svc._vector_store.update_metadata(first, {SOURCE_HASH_KEY: ""})
    again = svc.retain(DECISION, MemoryType.DECISION, source="src/a.py")
    assert again == first and svc.get(first).source_hash == ""


# ── SC-3c ────────────────────────────────────────────────────────────────────


def test_newest_recall_returns_a_flagged_decision_checkpoint_and_the_lifecycle_still_skips_it(tmp_path: Path) -> None:
    svc, settings = _service(tmp_path)
    path = _write(tmp_path, "src/redact.py", V1)
    decision = svc.retain(DECISION, MemoryType.DECISION, source="src/redact.py", checkpoint=True)
    code = svc.retain(V1, MemoryType.CODE, source="src/redact.py", checkpoint=True)
    path.write_text(V2, encoding="utf-8")
    svc.revalidate()

    newest = svc.recall("session checkpoint", checkpoint_only=True, order="newest", top_k=5)
    assert [r.ref_id for r in newest] == [decision]
    assert newest[0].needs_review is True and newest[0].review_reason == "changed"
    assert code not in {r.ref_id for r in newest}

    assert svc.checkpoints_newest_first() == []  # the default the lifecycle uses: no flagged record
    assert MemoryLifecycle(svc, settings)._latest_checkpoint_memory() is None


# ── D1: the session-start list ───────────────────────────────────────────────


def test_session_start_lists_a_flagged_decision_with_its_type(tmp_path: Path) -> None:
    svc, settings = _service(tmp_path)
    path = _write(tmp_path, "src/redact.py", V1)
    decision = svc.retain(DECISION, MemoryType.DECISION, source="src/redact.py")
    path.write_text(V2, encoding="utf-8")
    text = MemoryLifecycle(svc, settings).on_session_start("startup")
    assert f'{HEADING_NEEDS_REVIEW}\n- [decision] <stored-memory kind="review">src/redact.py</stored-memory>' in text
    assert f"— changed — {decision}" in text and "A decision: re-check its evidence" in text


# ── A1: the hook blocks' context lines mark flagged items ────────────────────


FLAGGED_LABEL = "[decision, needs review: changed]"


def _flagged_decision(tmp_path: Path) -> tuple[Any, MemKernelSettings, str]:
    svc, settings = _service(tmp_path)
    path = _write(tmp_path, "src/redact.py", V1)
    decision = svc.retain(DECISION, MemoryType.DECISION, source="src/redact.py")
    path.write_text(V2, encoding="utf-8")
    svc.revalidate()
    return svc, settings, decision


def _context_line(text: str, ref: str) -> str:
    return next(line for line in text.splitlines() if line.startswith("- [") and line.endswith(f"({ref})"))


def test_the_startup_block_marks_a_flagged_decision(tmp_path: Path) -> None:
    svc, settings, decision = _flagged_decision(tmp_path)
    text = MemoryLifecycle(svc, settings).on_session_start("startup")
    assert _context_line(text, decision).startswith(f"- {FLAGGED_LABEL} ")


def test_the_compaction_blocks_mark_a_flagged_decision(tmp_path: Path) -> None:
    svc, settings, decision = _flagged_decision(tmp_path)
    svc.retain("SESSION CHECKPOINT\nCurrent: redaction redact_text contract.", MemoryType.EPISODE, checkpoint=True)
    lifecycle = MemoryLifecycle(svc, settings)
    recovery = lifecycle.on_session_start("compact")
    assert _context_line(recovery, decision).startswith(f"- {FLAGGED_LABEL} ")
    post = lifecycle.on_post_compact()
    assert _context_line(post, decision).startswith(f"- {FLAGGED_LABEL} ")


def test_an_unflagged_decision_keeps_the_plain_label(tmp_path: Path) -> None:
    svc, settings = _service(tmp_path)
    _write(tmp_path, "src/redact.py", V1)
    decision = svc.retain(DECISION, MemoryType.DECISION, source="src/redact.py")
    text = MemoryLifecycle(svc, settings).on_session_start("startup")
    assert _context_line(text, decision).startswith("- [decision] ")


def test_session_start_lists_a_flag_whose_file_could_not_be_read_this_time(tmp_path: Path) -> None:
    svc, settings, decision = _flagged_decision(tmp_path)
    path = tmp_path / "src" / "redact.py"
    path.chmod(0)  # unreadable now: this pass reports unknown and keeps the flag
    try:
        report = svc.revalidate()
        assert report["unknown"] == 1 and report["flagged"] == []
        text = MemoryLifecycle(svc, settings).on_session_start("startup")
    finally:
        path.chmod(0o644)
    assert HEADING_NEEDS_REVIEW in text and f"— changed — {decision}" in text

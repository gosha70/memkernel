# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""The context diff (memkernel-0-15-harness-foundations H3: FR-004, SC-2; amendment C1–C9)."""

from __future__ import annotations

import importlib.util
import json
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import chromadb
import pytest

from memkernel import recall_log
from memkernel.config import MemKernelSettings
from memkernel.core.models import EVERYONE, NEEDS_REVIEW_KEY, REVIEW_REASON_KEY, Caller, MemoryType
from memkernel.factory import build_service
from tests.conftest import MockEmbedding

pytestmark = pytest.mark.unit

DIFF = Path(__file__).resolve().parents[2] / "eval" / "context-diff" / "diff.py"
RUN = "run-7"


def _load() -> Any:
    spec = importlib.util.spec_from_file_location("context_diff", DIFF)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


diff_module = _load()


@pytest.fixture
def env(tmp_path: Path) -> tuple[Any, MemKernelSettings, Path]:
    root = tmp_path / "project"
    root.mkdir()
    settings = MemKernelSettings(
        project_id=f"h3-{uuid.uuid4().hex[:8]}",
        chroma_persist_path=str(tmp_path / "chroma"),
        state_dir=str(tmp_path / "state"),
        project_root=str(root),
        recall_log=True,
        observation_ttl_days=7,
    )
    svc = build_service(settings, embedding=MockEmbedding(), chroma_client=chromadb.EphemeralClient())
    return svc, settings, root


def _receive(svc: Any, settings: MemKernelSettings, refs: list[str], **overrides: Any) -> None:
    """One recall-log record of the run, as an MCP recall writes it, with ``overrides`` per memory entry."""
    memories = [svc.get(ref, touch=False, caller=EVERYONE) for ref in refs]
    recall_log.append(settings, recall_log.ORIGIN_TOOL, refs, query="q", ids=recall_log.Correlation(RUN))
    if overrides:
        path = recall_log.log_path(settings)
        assert path is not None
        lines = path.read_text(encoding="utf-8").splitlines()
        record = json.loads(lines[-1])
        record["memories"] = [{**recall_log.receipt_entry(m), **overrides.get(m.ref_id, {})} for m in memories]
        lines[-1] = json.dumps(record)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    else:
        _rewrite_last(settings, lambda r: {**r, "memories": [recall_log.receipt_entry(m) for m in memories]})


def _rewrite_last(settings: MemKernelSettings, change: Any) -> None:
    path = recall_log.log_path(settings)
    assert path is not None
    lines = path.read_text(encoding="utf-8").splitlines()
    lines[-1] = json.dumps(change(json.loads(lines[-1])))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _report(svc: Any, settings: MemKernelSettings) -> dict[str, Any]:
    """The report with source checks on: the fixture's project folder as the root."""
    return diff_module.diff(settings, RUN, store=svc._vector_store, root=Path(settings.project_root))


def _statuses(svc: Any, settings: MemKernelSettings) -> dict[str, list[str]]:
    report = _report(svc, settings)
    assert report is not None
    return {m["ref_id"]: m["statuses"] for m in report["memories"]}


def test_sc2_a_superseded_decision_and_a_changed_code_file(env: Any) -> None:
    svc, settings, root = env
    (root / "app.py").write_text("def handler():\n    return 1\n", encoding="utf-8")
    decision = svc.retain("Use Postgres for the user store.", MemoryType.DECISION)
    code = svc.retain((root / "app.py").read_text(encoding="utf-8"), MemoryType.CODE, source="app.py")
    _receive(svc, settings, [decision, code])
    svc.retain("Use MySQL for the user store.", MemoryType.DECISION, supersedes=decision)
    (root / "app.py").write_text("def handler():\n    return 2\n", encoding="utf-8")
    statuses = _statuses(svc, settings)
    assert statuses == {decision: ["superseded"], code: ["source changed"]}


def test_an_untouched_memory_is_unchanged_and_the_report_holds_no_content(env: Any) -> None:
    svc, settings, _ = env
    fact = svc.retain("Secret-free fact: the API listens on 8080.", MemoryType.FACT)
    _receive(svc, settings, [fact])
    report = _report(svc, settings)
    assert report["memories"][0]["statuses"] == ["unchanged"] and "8080" not in json.dumps(report)
    assert report["counts"]["unchanged"] == 1 and report["records"] == 1


def test_a_deleted_or_expired_memory_is_missing_and_nothing_else(env: Any) -> None:
    svc, settings, _ = env
    gone = svc.retain("A fact to delete.", MemoryType.FACT)
    stale = svc.retain("A slow query on Monday.", MemoryType.OBSERVATION)
    _receive(svc, settings, [gone, stale])
    svc.forget(gone)
    svc._vector_store.update_metadata(stale, {"timestamp": (datetime.now(UTC) - timedelta(days=60)).isoformat()})
    assert _statuses(svc, settings) == {gone: ["missing"], stale: ["missing"]}


def test_withdrawn_changed_and_rehashed(env: Any) -> None:
    svc, settings, _ = env
    page = svc.retain("A wiki fact.", MemoryType.FACT)
    edited = svc.retain("A fact whose text the run saw differently.", MemoryType.FACT)
    rehashed = svc.retain("A fact hashed under a later scheme.", MemoryType.FACT)
    _receive(
        svc,
        settings,
        [page, edited, rehashed],
        **{edited: {"content_hash": "0" * 64}, rehashed: {"content_hash": "1" * 64, "content_hash_scheme": "canon"}},
    )
    svc.withdraw(page, "deprecated")
    statuses = _statuses(svc, settings)
    assert statuses == {page: ["withdrawn"], edited: ["changed"], rehashed: ["rehashed"]}


def test_flagged_is_judged_against_the_receipts_state(env: Any) -> None:
    svc, settings, _ = env
    newly = svc.retain("A fact flagged after the run.", MemoryType.FACT)
    already = svc.retain("A fact the run saw flagged.", MemoryType.FACT)
    svc._vector_store.update_metadata(already, {NEEDS_REVIEW_KEY: True, REVIEW_REASON_KEY: "changed"})
    _receive(svc, settings, [newly, already])
    svc._vector_store.update_metadata(newly, {NEEDS_REVIEW_KEY: True, REVIEW_REASON_KEY: "changed"})
    assert _statuses(svc, settings) == {newly: ["flagged"], already: ["unchanged"]}


def test_two_statuses_on_one_memory(env: Any) -> None:
    svc, settings, root = env
    (root / "notes.md").write_text("Postgres.\n", encoding="utf-8")
    decision = svc.retain("Use Postgres.", MemoryType.DECISION, source="notes.md")
    _receive(svc, settings, [decision])
    svc.retain("Use MySQL.", MemoryType.DECISION, supersedes=decision)
    (root / "notes.md").write_text("MySQL.\n", encoding="utf-8")
    assert _statuses(svc, settings) == {decision: ["superseded", "source changed"]}


def test_a_gone_file_counts_with_or_without_a_source_hash(env: Any) -> None:
    svc, settings, root = env
    for name in ("with.md", "without.md", "kept.md"):
        (root / name).write_text(f"{name}\n", encoding="utf-8")
    hashed = svc.retain("Decision citing with.md.", MemoryType.DECISION, source="with.md")
    unhashed = svc.retain("Decision citing without.md.", MemoryType.DECISION, source="without.md")
    present = svc.retain("Decision citing kept.md.", MemoryType.DECISION, source="kept.md")
    _receive(
        svc, settings, [hashed, unhashed, present], **{unhashed: {"source_hash": ""}, present: {"source_hash": ""}}
    )
    (root / "with.md").unlink()
    (root / "without.md").unlink()
    assert _statuses(svc, settings) == {
        hashed: ["source changed"],
        unhashed: ["source changed"],
        present: ["unchanged"],
    }


def test_a_source_outside_the_root_gets_no_check_and_says_so(env: Any) -> None:
    svc, settings, _ = env
    decision = svc.retain("Decision citing a file elsewhere.", MemoryType.DECISION, source="/etc/hosts")
    _receive(svc, settings, [decision])
    report = _report(svc, settings)
    (judged,) = report["memories"]
    assert judged["statuses"] == ["unchanged"] and judged["notes"] == [diff_module.NOTE_OUTSIDE_ROOT]


def test_a_chunk_is_judged_by_its_file_record_after_its_chunks_were_deleted(env: Any) -> None:
    svc, settings, root = env
    v1 = "def first():\n    return 1\n\n\ndef second():\n    return 2\n"
    (root / "lib.py").write_text(v1, encoding="utf-8")
    owner = svc.retain(v1, MemoryType.CODE, source="lib.py")
    chunks = [m for m in svc._vector_store.list_all({"parent_ref": owner}, include_content=False)]
    assert chunks, "the code chunker gives the snapshot chunk records"
    chunk = chunks[0].ref_id
    _receive(svc, settings, [chunk])
    v2 = v1.replace("return 2", "return 3")
    (root / "lib.py").write_text(v2, encoding="utf-8")
    svc.retain(v2, MemoryType.CODE, source="lib.py")
    assert svc._vector_store.get_by_id(chunk) is None  # the superseded snapshot's chunks are gone
    report = _report(svc, settings)
    (judged,) = report["memories"]
    assert judged["owner"] == owner and judged["statuses"] == ["superseded", "source changed"]


def test_unknown_combines_with_superseded_and_an_earlier_full_receipt_counts(env: Any) -> None:
    svc, settings, _ = env
    cut = svc.retain("Decision only in cut-down records.", MemoryType.DECISION)
    earlier = svc.retain("Decision with an earlier full receipt.", MemoryType.DECISION)
    _receive(svc, settings, [earlier])
    _receive(svc, settings, [cut, earlier])
    _rewrite_last(settings, lambda r: {**r, "memories": [], "memories_truncated": True, "truncated": True})
    svc.retain("A newer decision.", MemoryType.DECISION, supersedes=cut)
    assert _statuses(svc, settings) == {earlier: ["unchanged"], cut: ["superseded", "unknown"]}


def test_a_private_memory_is_judged_across_scopes(env: Any) -> None:
    svc, settings, _ = env
    private = svc.retain("Agent a's note.", MemoryType.FACT, scope="agent", caller=Caller(agent_id="a"))
    _receive(svc, settings, [private])
    report = _report(svc, settings)
    assert report["memories"][0]["statuses"] == ["unchanged"] and report["memories"][0]["scope"] == "agent:a"


def test_cut_short_ref_ids_add_a_note(env: Any) -> None:
    svc, settings, _ = env
    fact = svc.retain("A fact.", MemoryType.FACT)
    _receive(svc, settings, [fact])
    _rewrite_last(settings, lambda r: {**r, "ref_ids_truncated": True, "truncated": True})
    report = _report(svc, settings)
    assert report["notes"] == [
        "1 record(s) of this run had their ref_ids cut short: the run may have received memories not listed"
    ]
    assert "Note: 1 record(s)" in diff_module.render(report)


def test_exit_codes(env: Any, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    svc, settings, _ = env
    fact = svc.retain("A fact.", MemoryType.FACT)
    _receive(svc, settings, [fact])
    spec = f"chroma={settings.chroma_persist_path},state={settings.state_dir},project={settings.project_id}"
    Path(settings.chroma_persist_path).mkdir(parents=True, exist_ok=True)  # a store folder the command line opens
    out = tmp_path / "report.json"
    assert diff_module.main(["--store", spec, "--run", RUN, "--json", str(out)]) == 0
    assert json.loads(out.read_text(encoding="utf-8"))["run_id"] == RUN
    assert diff_module.main(["--store", spec, "--run", "no-such-run"]) == 1
    assert "No recall-log record carries run_id" in capsys.readouterr().out
    with pytest.raises(SystemExit) as missing_store:
        diff_module.main(["--store", "chroma=/nonexistent,state=/x,project=p", "--run", RUN])
    assert missing_store.value.code == 2
    with pytest.raises(SystemExit) as bad_spec:
        diff_module.main(["--store", "chroma=/x", "--run", RUN])
    assert bad_spec.value.code == 2


def test_without_a_root_source_checks_are_skipped_and_said_so(env: Any) -> None:
    svc, settings, root = env
    (root / "notes.md").write_text("v1\n", encoding="utf-8")
    decision = svc.retain("Decision citing notes.md.", MemoryType.DECISION, source="notes.md")
    _receive(svc, settings, [decision])
    (root / "notes.md").unlink()
    report = diff_module.diff(settings, RUN, store=svc._vector_store)
    (judged,) = report["memories"]
    assert judged["statuses"] == ["unchanged"] and judged["notes"] == ["no source check (no root given)"]
    assert report["root"] is None and "Root: none given, so no source checks" in diff_module.render(report)
    with_root = _report(svc, settings)
    assert with_root["memories"][0]["statuses"] == ["source changed"]
    assert with_root["root"] == str(root) and f"Root: {root}" in diff_module.render(with_root)


def test_unreadable_log_files_are_counted_and_make_the_log_incomplete(
    env: Any, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    svc, settings, _ = env
    fact = svc.retain("A fact.", MemoryType.FACT)
    _receive(svc, settings, [fact])
    path = recall_log.log_path(settings)
    assert path is not None
    path.with_name(f"{path.name}.1").write_bytes(b"\xff\xfe not utf-8 \xff")
    report = _report(svc, settings)
    assert report["unreadable_log_files"] == 1
    assert "1 log file(s) could not be read and were skipped: the log is incomplete" in report["notes"]
    Path(settings.chroma_persist_path).mkdir(parents=True, exist_ok=True)
    spec = f"chroma={settings.chroma_persist_path},state={settings.state_dir},project={settings.project_id}"
    assert diff_module.main(["--store", spec, "--run", "no-such-run"]) == 1
    assert "1 log file(s) could not be read, so the log is incomplete" in capsys.readouterr().out


def test_a_chunk_from_before_0_4_is_judged_by_the_record_that_lists_it(env: Any) -> None:
    """Revalidation's rule: a record a code record's chunk_refs lists is a chunk of it, though it has no parent_ref."""
    svc, settings, root = env
    source = "def legacy():\n    return 1\n"
    (root / "old.py").write_text(source, encoding="utf-8")
    owner = svc.retain(source, MemoryType.CODE, source="old.py")
    legacy = "legacy-0-3-chunk"  # an id from before 0.4: no <owner>-chunk-<n> form
    svc._vector_store.upsert(
        ref_id=legacy,
        content="return 1",
        embedding=MockEmbedding().embed(["return 1"])[0],
        metadata={
            "project_id": settings.project_id,
            "session_id": "default",
            "timestamp": datetime.now(UTC).isoformat(),
            "type": "code",
            "source": "old.py",
            "hash": "c" * 64,
            "token_count": 1,
            "code_chunk": True,
        },
    )
    svc._vector_store.update_metadata(owner, {"chunk_refs": legacy})
    _receive(svc, settings, [legacy])
    (root / "old.py").write_text("def legacy():\n    return 2\n", encoding="utf-8")
    report = _report(svc, settings)
    (judged,) = report["memories"]
    assert judged["owner"] == owner and judged["statuses"] == ["source changed"]

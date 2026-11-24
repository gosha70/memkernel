# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""Scope and abstention (memkernel-0-15-harness-foundations H2: FR-001, FR-005, SC-1, SC-4, SC-6; B1–B11)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import chromadb
import pytest

from memkernel import session_spool
from memkernel.config import MemKernelSettings
from memkernel.core.models import (
    CAPTURE_ORIGIN_TAG,
    CAPTURE_SESSION_TAG,
    EVERYONE,
    NEEDS_REVIEW_KEY,
    REVIEW_REASON_KEY,
    SCOPE_KEY,
    Caller,
    MemoryType,
    RecallReceipt,
)
from memkernel.factory import build_service
from memkernel.lifecycle import SESSION_TAG_PREFIX, MemoryLifecycle
from memkernel.wiki.sync import WikiExporter
from tests.conftest import MockEmbedding

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit

A = Caller(agent_id="a")
B = Caller(agent_id="b")
NOBODY = Caller()


def _settings(tmp_path: Path, **overrides: Any) -> MemKernelSettings:
    base: dict[str, Any] = {
        "project_id": f"h2-{uuid.uuid4().hex[:8]}",
        "chroma_persist_path": str(tmp_path / "chroma"),
        "state_dir": str(tmp_path / "state"),
    }
    base.update(overrides)
    return MemKernelSettings(**base)


def _service(settings: MemKernelSettings) -> Any:
    return build_service(settings, embedding=MockEmbedding(), chroma_client=chromadb.EphemeralClient())


def _ids(refs: list[Any]) -> set[str]:
    return {r.ref_id for r in refs}


@pytest.fixture
def svc(tmp_path: Path) -> Any:
    return _service(_settings(tmp_path))


# --- SC-1: every read path ----------------------------------------------------------------------------------------


def test_recall_returns_project_records_and_the_callers_own_only(svc: Any) -> None:
    shared = svc.retain("The build cache lives in /var/cache/build.", MemoryType.FACT)
    mine = svc.retain("The build cache needs a warm-up for agent a.", MemoryType.FACT, scope="agent", caller=A)
    assert _ids(svc.recall("build cache", top_k=10, caller=A)) == {shared, mine}
    assert _ids(svc.recall("build cache", top_k=10, caller=B)) == {shared}
    assert _ids(svc.recall("build cache", top_k=10, caller=NOBODY)) == {shared}


def test_get_ask_and_list_do_not_show_another_agents_record(svc: Any) -> None:
    mine = svc.retain("Agent a's scratch note on the parser.", MemoryType.FACT, scope="agent", caller=A)
    assert svc.get(mine, caller=A) is not None and svc.get(mine, caller=B) is None
    assert svc.ask(mine, "what is it?", caller=B) is None and svc.ask(mine, "what is it?", caller=A) is not None
    assert mine in {m.ref_id for m in svc.list_memories(caller=A)}
    assert mine not in {m.ref_id for m in svc.list_memories(caller=B)}
    assert mine not in {m.ref_id for m in svc.list_memories(caller=NOBODY)}


def test_promotion_candidates_are_the_callers(svc: Any) -> None:
    mine = svc.retain("Agent a saw the flaky test twice.", MemoryType.OBSERVATION, scope="agent", caller=A)
    shared = svc.retain("The nightly job failed once.", MemoryType.OBSERVATION)
    candidates_b = {c["ref_id"] for c in svc.consolidate(purge=False, caller=B)["candidates"]}
    candidates_a = {c["ref_id"] for c in svc.consolidate(purge=False, caller=A)["candidates"]}
    assert shared in candidates_b and mine not in candidates_b and {shared, mine} <= candidates_a


def test_the_session_start_block_shows_only_what_the_process_may_see(tmp_path: Path) -> None:
    settings = _settings(tmp_path, agent_id="b")
    svc = _service(settings)
    svc.retain("Deploys go out on Tuesdays.", MemoryType.DECISION)
    svc.retain("Agent a decided to rename the parser module.", MemoryType.DECISION, scope="agent", caller=A)
    svc.retain("SESSION CHECKPOINT\nDone: agent a's half.", MemoryType.EPISODE, checkpoint=True, caller=A)
    flagged = svc.retain("Agent a's parser lives in parse.py.", MemoryType.FACT, scope="agent", caller=A)
    svc._vector_store.update_metadata(flagged, {NEEDS_REVIEW_KEY: True, REVIEW_REASON_KEY: "changed"})
    svc.retain("Agent a keeps retrying the build.", MemoryType.OBSERVATION, scope="agent", caller=A)
    text = MemoryLifecycle(svc, settings).on_session_start("startup", session_id="s1")
    assert "Deploys go out on Tuesdays." in text
    assert "agent a" not in text.lower() and flagged not in text
    assert "No checkpoint found yet" in text


def test_wiki_export_drafts_project_records_only_whoever_calls(tmp_path: Path) -> None:
    """B3: even agent a's own export leaves its private decision out."""
    settings = _settings(tmp_path, agent_id="a", wiki_mode="ungated")
    svc = _service(settings)
    svc.retain("Use Postgres for the user store.", MemoryType.DECISION)
    svc.retain("Agent a prefers SQLite for its prototype.", MemoryType.DECISION, scope="agent")
    report = WikiExporter(svc, tmp_path / "wiki").export()
    assert report.written == ["decisions/use-postgres-for-the-user-store.md"]


# --- B4: checkpoints follow the effective scope ------------------------------------------------------------------


def test_a_checkpoint_goes_to_the_task_then_the_agent_then_the_project(svc: Any) -> None:
    on_task = svc.retain("SESSION CHECKPOINT\nDone: t1.", MemoryType.EPISODE, checkpoint=True, caller=Caller("a", "t1"))
    on_agent = svc.retain("SESSION CHECKPOINT\nDone: a.", MemoryType.EPISODE, checkpoint=True, caller=A)
    shared = svc.retain("SESSION CHECKPOINT\nDone: shared.", MemoryType.EPISODE, checkpoint=True, caller=NOBODY)
    assert [svc.get(r, touch=False, caller=EVERYONE).scope for r in (on_task, on_agent, shared)] == [
        "task:t1",
        "agent:a",
        "project",
    ]
    explicit = svc.retain(
        "SESSION CHECKPOINT\nHandoff.", MemoryType.EPISODE, checkpoint=True, scope="project", caller=A
    )
    assert svc.get(explicit, touch=False).scope == "project"


def test_latest_checkpoint_recovery_reads_only_the_effective_scope(svc: Any) -> None:
    on_task = svc.retain("SESSION CHECKPOINT\nDone: t1.", MemoryType.EPISODE, checkpoint=True, caller=Caller("a", "t1"))
    handoff = svc.retain(
        "SESSION CHECKPOINT\nHandoff for anyone.", MemoryType.EPISODE, checkpoint=True, scope="project", caller=A
    )

    def newest(caller: Caller) -> tuple[list[str], str | None]:
        receipt = RecallReceipt()
        refs = svc.recall("checkpoint", checkpoint_only=True, order="newest", top_k=1, caller=caller, receipt=receipt)
        return [r.ref_id for r in refs], receipt.empty_reason

    assert newest(Caller("a", "t1")) == ([on_task], None)
    assert newest(A) == ([], "out_of_scope")  # agent a without the task: no fallback to the task or the project
    assert newest(NOBODY) == ([handoff], None)  # a caller with no ids recovers project checkpoints
    assert handoff in _ids(svc.recall("handoff", top_k=5, caller=B))  # the shared handoff, through relevance recall


def test_the_hooks_recover_and_save_in_the_processes_effective_scope(tmp_path: Path) -> None:
    settings = _settings(tmp_path, agent_id="a", task_id="t1")
    svc = _service(settings)
    svc.retain("SESSION CHECKPOINT\nDone: someone else's work.", MemoryType.EPISODE, checkpoint=True, caller=B)
    lifecycle = MemoryLifecycle(svc, settings)
    assert "No checkpoint found yet" in lifecycle.on_session_start("startup", session_id="s1")
    lifecycle.on_session_end("Done: t1's parser.")
    (saved,) = svc.checkpoints_newest_first(scope="task:t1")
    assert "t1's parser" in lifecycle.on_session_start("startup", session_id="s2") and saved.scope == "task:t1"


def test_an_unsaved_session_counts_a_checkpoint_in_any_scope(tmp_path: Path) -> None:
    """B8: the startup report is store-wide; a session saved under another task id is not reported unsaved."""
    settings = _settings(tmp_path, task_id="other")
    svc = _service(settings)
    now = datetime.now(UTC)
    for session_id in ("saved-elsewhere", "unsaved"):
        session_spool.append(settings, session_spool.EVENT_STARTED, session_id, now - timedelta(hours=2))
        session_spool.append(settings, session_spool.EVENT_ENDED, session_id, now - timedelta(hours=1), reason="other")
    svc.retain(
        "SESSION CHECKPOINT\nDone: x.",
        MemoryType.EPISODE,
        checkpoint=True,
        tags=[f"{SESSION_TAG_PREFIX}saved-elsewhere"],
        caller=Caller(task_id="x"),
    )
    text = MemoryLifecycle(svc, settings).on_session_start("startup", session_id="current")
    assert text.count("ended without a saved checkpoint") == 1


# --- B1, B9: writes ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("scope", "caller", "message"),
    [
        ("agent", NOBODY, "needs the caller's agent_id"),
        ("task", A, "needs the caller's task_id"),
        ("agent:b", A, "scope must be"),
    ],
)
def test_retain_names_only_the_callers_own_scope(svc: Any, scope: str, caller: Caller, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        svc.retain("A note.", MemoryType.FACT, scope=scope, caller=caller)


def test_dedup_is_per_scope_and_an_older_record_counts_as_project(svc: Any) -> None:
    shared = svc.retain("The API listens on port 8080.", MemoryType.FACT)
    stored = svc._vector_store._collection.get(ids=[shared], include=["metadatas"])["metadatas"][0]
    assert SCOPE_KEY not in stored  # SC-4: written as an older store writes it
    mine = svc.retain("The API listens on port 8080.", MemoryType.FACT, scope="agent", caller=A)
    again = svc.retain("The API listens on port 8080.", MemoryType.FACT, scope="project", caller=A)
    assert mine != shared and again == shared
    assert svc.get(shared, caller=B).scope == "project"


def test_promote_keeps_the_scope_and_publishes_only_when_asked(svc: Any) -> None:
    note = svc.retain("Agent a found the retry limit is 5.", MemoryType.OBSERVATION, scope="agent", caller=A)
    kept = svc.promote(note, MemoryType.FACT, caller=A)
    published = svc.promote(note, MemoryType.FACT, content="The retry limit is 5.", scope="project", caller=A)
    assert svc.get(kept, caller=A).scope == "agent:a" and svc.get(kept, caller=B) is None
    assert svc.get(published, caller=B).scope == "project"
    assert svc.promote(note, MemoryType.FACT, caller=B) is None  # B2: not found


def test_a_private_record_supersedes_only_its_own_scope(svc: Any) -> None:
    decision = svc.retain("Use Postgres.", MemoryType.DECISION)
    with pytest.raises(ValueError, match="supersedes only records in its own scope"):
        svc.retain("Use SQLite here.", MemoryType.DECISION, scope="agent", supersedes=decision, caller=A)
    assert svc.get(decision, touch=False).superseded_by is None
    draft = svc.retain("Agent a: maybe MySQL.", MemoryType.DECISION, scope="agent", caller=A)
    newer = svc.retain("Agent a: MySQL, final.", MemoryType.DECISION, scope="agent", supersedes=draft, caller=A)
    assert svc.get(draft, touch=False, caller=A).superseded_by == newer
    published = svc.retain("Use MySQL for reports.", MemoryType.DECISION, supersedes=newer, caller=A)
    assert svc.get(newer, touch=False, caller=A).superseded_by == published  # project over the caller's own


def test_an_unseen_supersede_target_is_ignored_and_a_missing_one_keeps_its_link(svc: Any) -> None:
    private = svc.retain("Agent a: use MySQL.", MemoryType.DECISION, scope="agent", caller=A)
    over = svc.retain("Use Postgres everywhere.", MemoryType.DECISION, supersedes=private, caller=B)
    assert svc.get(private, touch=False, caller=A).superseded_by is None
    assert svc.get(over, touch=False).supersedes is None  # no link to a record its writer could not see
    dangling = svc.retain("Use arq.", MemoryType.DECISION, supersedes="ghost", caller=B)
    assert svc.get(dangling, touch=False).supersedes == "ghost"  # as before: health reports it dangling


def test_forget_cannot_delete_another_agents_record(svc: Any) -> None:
    mine = svc.retain("Agent a's note.", MemoryType.FACT, scope="agent", caller=A)
    assert svc.forget(mine, caller=B) is False and svc.get(mine, caller=A) is not None
    assert svc.forget(mine, caller=A) is True


def test_code_keeps_one_live_snapshot_per_source_and_scope(svc: Any) -> None:
    def code(version: int) -> str:
        return f"def handler():\n    return {version}\n"

    a1 = svc.retain(code(1), MemoryType.CODE, source="app.py", scope="agent", caller=A)
    b2 = svc.retain(code(2), MemoryType.CODE, source="app.py", caller=B)
    assert svc.get(a1, touch=False, caller=A).superseded_by is None  # b cannot see a1: it stays live
    a3 = svc.retain(code(3), MemoryType.CODE, source="app.py", scope="agent", caller=A)
    assert svc.get(a1, touch=False, caller=A).superseded_by == a3
    assert svc.get(b2, touch=False).superseded_by is None  # a private snapshot replaces only its scope
    a4 = svc.retain(code(4), MemoryType.CODE, source="app.py", caller=A)
    assert svc.get(b2, touch=False).superseded_by == a4 and svc.get(a3, touch=False, caller=A).superseded_by == a4


def test_a_document_chunk_resolves_only_to_a_summary_the_caller_can_see(svc: Any) -> None:
    body = "# Runbook\n\n" + "\n\n".join(f"Step {i}: restart the zeta-quorum service." for i in range(30))
    doc = svc.retain(body, MemoryType.DOCUMENT, source="runbook.md", scope="agent", caller=A)
    assert doc in _ids(svc.recall("zeta-quorum", top_k=5, caller=A))
    receipt = RecallReceipt()
    assert svc.recall("zeta-quorum", top_k=5, caller=B, receipt=receipt) == []
    assert receipt.excluded is not None and receipt.excluded["out_of_scope"] >= 1
    assert receipt.empty_reason == "out_of_scope"


# --- B5, B10, B11: filtering, counts, abstention ------------------------------------------------------------------


def test_recall_widens_past_out_of_scope_candidates(svc: Any) -> None:
    for i in range(15):
        svc.retain(f"alpha note {i} for agent a only", MemoryType.FACT, scope="agent", caller=A)
    shared = svc.retain("alpha note for everyone", MemoryType.FACT)
    receipt = RecallReceipt()
    assert [r.ref_id for r in svc.recall("alpha note", top_k=1, caller=B, receipt=receipt)] == [shared]
    assert receipt.excluded is not None and receipt.excluded["out_of_scope"] >= 1 and receipt.empty_reason is None


def test_each_exclusion_is_counted_once_in_order_and_capped_is_counted(svc: Any) -> None:
    hidden = svc.retain("disk quota alert for agent a", MemoryType.FACT, scope="agent", caller=A)
    old = svc.retain("disk quota is 10 GB", MemoryType.DECISION, scope="agent", caller=A)
    svc.retain("disk quota is 20 GB", MemoryType.DECISION, scope="agent", supersedes=old, caller=A)
    for i in range(4):
        svc.retain(
            f"captured disk quota warning {i}",
            MemoryType.OBSERVATION,
            tags=[CAPTURE_ORIGIN_TAG, f"{CAPTURE_SESSION_TAG}s1"],
        )
    receipt = RecallReceipt()
    results = svc.recall("disk quota", top_k=20, caller=B, receipt=receipt)
    assert hidden not in _ids(results) and old not in _ids(results)
    assert receipt.excluded == {"out_of_scope": 3, "superseded": 0, "flagged": 0, "expired": 0, "capped": 1}


def test_an_empty_recall_says_why(svc: Any) -> None:
    receipt = RecallReceipt()
    assert svc.recall("nothing stored at all", top_k=3, caller=B, receipt=receipt) == []
    assert receipt.empty_reason == "no_match"
    svc.retain("kappa-only private fact", MemoryType.FACT, scope="agent", caller=A)
    assert svc.recall("kappa-only private fact", top_k=3, caller=B, receipt=receipt) == []
    assert receipt.empty_reason == "out_of_scope"
    flagged = svc.retain("kappa-only shared fact", MemoryType.FACT)
    svc._vector_store.update_metadata(flagged, {NEEDS_REVIEW_KEY: True, REVIEW_REASON_KEY: "changed"})
    assert svc.recall("kappa-only", top_k=3, caller=B, receipt=receipt) == []
    assert receipt.empty_reason == "excluded"
    newest = RecallReceipt()
    assert svc.recall("x", checkpoint_only=True, order="newest", caller=B, receipt=newest) == []
    assert newest.empty_reason == "no_match"


# --- B8: store maintenance stays store-wide ----------------------------------------------------------------------


def test_the_purge_removes_expired_private_records_whoever_runs_it(tmp_path: Path) -> None:
    svc = _service(_settings(tmp_path, observation_ttl_days=7))
    mine = svc.retain("Agent a saw a slow query.", MemoryType.OBSERVATION, scope="agent", caller=A)
    svc._vector_store.update_metadata(mine, {"timestamp": (datetime.now(UTC) - timedelta(days=60)).isoformat()})
    assert svc.consolidate(caller=B)["purged"] == 1 and svc.get(mine, caller=A) is None


def test_stats_count_every_record(svc: Any) -> None:
    """B7: the admin API's view is the operator's, store-wide."""
    svc.retain("Shared fact.", MemoryType.FACT)
    svc.retain("Agent a's fact.", MemoryType.FACT, scope="agent", caller=A)
    assert svc.stats()["total"] == 2 and len(svc.list_memories(caller=EVERYONE)) == 2


def test_compaction_recovery_reads_only_the_processes_effective_scope(tmp_path: Path) -> None:
    settings = _settings(tmp_path, agent_id="b")
    svc = _service(settings)
    svc.retain("SESSION CHECKPOINT\nDone: agent a's migration.", MemoryType.EPISODE, checkpoint=True, caller=A)
    mine = svc.retain("SESSION CHECKPOINT\nDone: agent b's tests.", MemoryType.EPISODE, checkpoint=True, caller=B)
    text = MemoryLifecycle(svc, settings).on_session_start("compact", session_id="s1")
    assert mine in text and "agent b's tests" in text and "agent a's migration" not in text


def test_a_shared_body_is_found_through_each_owners_own_summary(svc: Any) -> None:
    """Document parts carry no scope: each owner's summary decides who finds the body (B9)."""
    body = "# Guide\n\n" + "\n\n".join(f"Section {i}: tune the omega-pool size." for i in range(30))
    private = svc.retain(body, MemoryType.DOCUMENT, source="guide.md", scope="agent", caller=A)
    shared = svc.retain(body, MemoryType.DOCUMENT, source="guide.md", caller=B)
    assert private != shared
    assert _ids(svc.recall("omega-pool", top_k=5, caller=B)) == {shared}
    assert _ids(svc.recall("omega-pool", top_k=5, caller=A)) & {private, shared}


def test_another_agents_private_promotion_leaves_the_shared_source_a_candidate(svc: Any) -> None:
    source = svc.retain("The staging DB restarts nightly.", MemoryType.OBSERVATION)
    svc.promote(source, MemoryType.FACT, scope="agent", caller=A)
    assert source not in {c["ref_id"] for c in svc.consolidate(purge=False, caller=A)["candidates"]}
    assert source in {c["ref_id"] for c in svc.consolidate(purge=False, caller=B)["candidates"]}


def test_flags_found_by_this_pass_are_shown_only_to_who_can_see_them(tmp_path: Path) -> None:
    """B8: revalidation runs store-wide and counts every record, but lists only what the caller can see; the session
    start (which revalidates) and consolidate(revalidate=True) both go through it."""
    root = tmp_path / "project"
    root.mkdir()
    (root / "design-notes.md").write_text("Use the v1 API.\n", encoding="utf-8")
    client = chromadb.EphemeralClient()
    settings_a = _settings(tmp_path, project_root=str(root), agent_id="a")
    settings_b = settings_a.model_copy(update={"agent_id": "b"})
    svc_a = build_service(settings_a, embedding=MockEmbedding(), chroma_client=client)
    svc_b = build_service(settings_b, embedding=MockEmbedding(), chroma_client=client)
    decision = svc_a.retain("Agent a: call the v1 API.", MemoryType.DECISION, source="design-notes.md", scope="agent")
    (root / "design-notes.md").write_text("Use the v2 API.\n", encoding="utf-8")

    report_b = svc_b.consolidate(revalidate=True)["revalidated"]
    assert report_b["changed"] == 1 and report_b["flagged"] == []
    text_b = MemoryLifecycle(svc_b, settings_b).on_session_start("startup", session_id="b1")
    assert decision not in text_b and "design-notes.md" not in text_b

    report_a = svc_a.consolidate(revalidate=True)["revalidated"]
    assert [item["ref_id"] for item in report_a["flagged"]] == [decision]
    assert decision in MemoryLifecycle(svc_a, settings_a).on_session_start("startup", session_id="a1")

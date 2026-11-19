# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""S3 capture signals: owner answers and session outcomes (memkernel-0-14-capture-signals, #147)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from memkernel import capture
from memkernel.core.models import (
    CAPTURE_CALL_TAG,
    CAPTURE_EXTRACTOR_TAG,
    CAPTURE_ORIGIN_TAG,
    CAPTURE_SESSION_TAG,
    MemoryTier,
    MemoryType,
    ToolStep,
    TranscriptSession,
)
from memkernel.transcripts.claude_code import ClaudeCodeTranscriptReader
from tests.unit.test_capture import FIXED, _captured, _setup, _spooled_sessions

pytestmark = pytest.mark.unit

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "transcripts"
T0 = datetime(2026, 11, 18, 10, 0, tzinfo=UTC)
READER = ClaudeCodeTranscriptReader()


def _read(name: str) -> TranscriptSession:
    (session,) = READER.read(FIXTURES / f"{name}.jsonl")
    return session


def _step(tool: str, result: str = "", **fields: Any) -> ToolStep:
    return ToolStep(tool_use_id=fields.pop("call", tool), time=T0, tool=tool, has_result=True, result=result, **fields)


def _session(*steps: ToolStep) -> TranscriptSession:
    return TranscriptSession(session_id="s", start=T0, end=T0, steps=list(steps))


# ── owner answers (FR-001, FR-002; SC-1) ───────────────────────────────────


def test_a_real_call_with_an_option_and_the_owners_own_words_yields_two_records() -> None:
    session = _read("owner-answers")
    (step,) = session.steps
    assert len(step.questions) == 2 and len(step.answers) == 2  # read from toolUseResult (FR-001)
    first, second = capture.extract_owner_answers(session)
    assert (first.call, second.call) == (f"{step.tool_use_id}#0", f"{step.tool_use_id}#1")
    assert first.extractor == capture.OWNER_ANSWER and first.memory_type == MemoryType.EPISODE  # D3
    assert first.content.startswith("The owner's answer (Entrypoint): How should the new discovery commands")
    assert (
        "-> Unified cct CLI (" in first.content and "Other options offered: Claude Code slash commands" in first.content
    )
    assert "-> in their own words: I want 1 & 2." in second.content  # D2
    assert "Options offered: README rewrite; Generated feature index" in second.content


def test_a_real_multi_select_answer_is_one_record_naming_every_chosen_option_in_offered_order() -> None:
    (signal,) = capture.extract_owner_answers(_read("owner-answer-multiselect"))
    content = signal.content
    chosen = ["Fix issue #58 link (", "Draft 2 follow-up issues (", "Post-merge doc fixes ("]
    positions = [content.index(c) for c in chosen]
    assert positions == sorted(positions)
    assert content.endswith("Other options offered: Clean main checkout.")


def test_answers_are_redacted_and_the_owners_words_kept_longer_than_a_command() -> None:
    words = "use AKIAABCDEFGHIJKLMNOP for staging; " + "x" * 500
    step = _step(
        "AskUserQuestion",
        "ok",
        questions=[{"question": "Which key?", "header": "Key", "options": [{"label": "A"}]}],
        answers={"Which key?": words},
    )
    (signal,) = capture.extract_owner_answers(_session(step))
    assert "AKIA" not in signal.content and capture.REDACTED in signal.content
    assert len(signal.content) > capture.CAPTURE_TEXT_MAX


def test_a_sidechain_question_and_an_unanswered_question_yield_nothing() -> None:
    q = [{"question": "Q?", "options": [{"label": "A"}]}]
    side = _step("AskUserQuestion", questions=q, answers={"Q?": "A"}, sidechain=True, agent_id="ag")
    unanswered = _step("AskUserQuestion", call="u", questions=q, answers={"Other?": "A"})
    assert capture.extract_owner_answers(_session(side, unanswered)) == []


# ── session outcomes (FR-003; SC-2) ────────────────────────────────────────


def test_a_real_gh_session_yields_one_outcome_and_its_pr_view_is_ignored() -> None:
    session = _read("session-outcome-gh")
    (signal,) = capture.extract_outcome(session)
    assert signal.extractor == capture.SESSION_OUTCOME and signal.call == capture.OUTCOME_KEY
    assert signal.memory_type == MemoryType.EPISODE
    assert "opened PR https://github.com/example/memkernel/pull/92" in signal.content
    assert "filed issue https://github.com/example/memkernel/issues/128" in signal.content
    assert "edited 3 file(s): " in signal.content
    assert signal.content.count("https://github.com/") == 2  # the gh pr view read named other URLs: not counted


def test_github_mcp_creates_and_a_url_less_merge_count_and_reads_do_not() -> None:
    """GitHub's MCP tool shapes as documented (the local transcripts hold no GitHub MCP calls)."""
    steps = [
        _step(
            "mcp__github__create_pull_request",
            json.dumps({"number": 7, "html_url": "https://github.com/o/r/pull/7"}),
            call="a",
            tool_input={"owner": "o", "repo": "r", "title": "t"},
        ),
        _step(
            "mcp__github__issue_write",
            json.dumps({"html_url": "https://github.com/o/r/issues/8"}),
            call="b",
            tool_input={"method": "create", "owner": "o", "repo": "r"},
        ),
        _step(
            "mcp__github__merge_pull_request",
            json.dumps({"merged": True, "message": "Pull Request successfully merged"}),
            call="c",
            tool_input={"owner": "o", "repo": "r", "pullNumber": 6},
        ),
        _step("mcp__github__pull_request_read", '{"html_url": "https://github.com/o/r/pull/1"}', call="d"),
        _step("mcp__github__list_pull_requests", '[{"html_url": "https://github.com/o/r/pull/2"}]', call="e"),
        _step("mcp__github__issue_read", '{"html_url": "https://github.com/o/r/issues/3"}', call="f"),
    ]
    (signal,) = capture.extract_outcome(_session(*steps))
    assert signal.content == (
        "Session outcome: opened PR https://github.com/o/r/pull/7; merged PR https://github.com/o/r/pull/6; "
        "filed issue https://github.com/o/r/issues/8."
    )


def test_a_session_that_only_read_prs_or_did_nothing_has_no_outcome() -> None:
    reads = [
        _step("mcp__github__pull_request_read", '{"html_url": "https://github.com/o/r/pull/1"}', call="a"),
        _step("mcp__github__list_pull_requests", '[{"html_url": "https://github.com/o/r/pull/2"}]', call="b"),
        _step("mcp__github__issue_read", '{"html_url": "https://github.com/o/r/issues/3"}', call="c"),
        _step("Bash", "https://github.com/o/r/pull/4", call="d", command="gh pr view 4 --json url"),
    ]
    assert capture.extract_outcome(_session(*reads)) == []
    assert capture.extract_outcome(_session(_step("Bash", "ok", command="ls"))) == []


@pytest.mark.parametrize(
    ("command", "result", "url"),
    [
        ("gh pr merge 140 -R o/r --squash", "", "https://github.com/o/r/pull/140"),
        ("gh pr merge https://github.com/o/r/pull/9 --merge", "", "https://github.com/o/r/pull/9"),
        ("gh pr merge 5", "✓ Squashed and merged pull request o/r#5 (title)", "https://github.com/o/r/pull/5"),
        ("gh pr merge 11 2>&1 | tail -1", "✓ Merged", "https://github.com/x/y/pull/11"),  # the session's repository
    ],
)
def test_a_gh_merge_gets_its_url_from_its_input(command: str, result: str, url: str) -> None:
    seen = _step("Bash", "https://github.com/x/y/pull/10", call="v", command="gh pr view 10")  # names the repository
    (signal,) = capture.extract_outcome(_session(seen, _step("Bash", result, call="m", command=command)))
    assert f"merged PR {url}" in signal.content


def test_edited_files_are_named_up_to_the_limit_then_counted() -> None:
    edits = [_step("Edit", "ok", call=f"e{i}", file_path=f"src/f{i}.py") for i in range(13)]
    edits.append(_step("Edit", "ok", call="dup", file_path="src/f0.py"))
    (signal,) = capture.extract_outcome(_session(*edits))
    assert "edited 13 file(s): src/f0.py, " in signal.content and signal.content.endswith("(and 3 more).")


# ── the startup run: caps, keys, report (FR-004, FR-006; SC-3) ─────────────


def _ask_lines(session_id: str, start: int, count: int) -> list[dict[str, Any]]:
    """``count`` AskUserQuestion calls, one question each, answered with an offered option."""
    lines: list[dict[str, Any]] = []
    for i in range(start, start + count):
        question = {"question": f"Question {i}?", "header": f"H{i}", "options": [{"label": f"Option {i}"}]}
        use = {"type": "tool_use", "id": f"{session_id}-q{i}", "name": "AskUserQuestion", "input": {}}
        result = {"type": "tool_result", "tool_use_id": f"{session_id}-q{i}", "content": "answered"}
        lines.append({"sessionId": session_id, "timestamp": "2026-11-18T10:00:00Z", "message": {"content": [use]}})
        lines.append(
            {
                "sessionId": session_id,
                "timestamp": "2026-11-18T10:00:01Z",
                "message": {"content": [result]},
                "toolUseResult": {"questions": [question], "answers": {f"Question {i}?": f"Option {i}"}},
            }
        )
    return lines


def _write_session(t: Any, session_id: str, lines: list[dict[str, Any]]) -> None:
    path = t.root / f"{session_id}.jsonl"
    path.write_text("".join(json.dumps(line) + "\n" for line in lines), encoding="utf-8")
    t.spool(session_id, path)


def _calls(svc: Any, extractor: str) -> list[str]:
    tag = f"{CAPTURE_EXTRACTOR_TAG}{extractor}"
    return sorted(
        t[len(CAPTURE_CALL_TAG) :]
        for m in _captured(svc)
        if tag in m.tags
        for t in m.tags
        if t.startswith(CAPTURE_CALL_TAG)
    )


def test_a_session_keeps_its_last_30_answers_the_same_30_on_a_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lifecycle, svc, t = _setup(tmp_path)
    _write_session(t, "s1", _ask_lines("s1", 0, 35))
    from memkernel import session_spool

    real_commit = session_spool.commit
    monkeypatch.setattr(session_spool, "commit", lambda *_: (_ for _ in ()).throw(RuntimeError("killed")))
    lifecycle.on_session_start("startup", session_id="now")  # stored, then killed before the commit
    first = _calls(svc, capture.OWNER_ANSWER)
    monkeypatch.setattr(session_spool, "commit", real_commit)
    text = lifecycle.on_session_start("startup", session_id="now")
    assert first == _calls(svc, capture.OWNER_ANSWER) == sorted(f"s1-q{i}#0" for i in range(5, 35))
    assert "s1" not in _spooled_sessions(lifecycle._settings)
    assert len(_calls(svc, capture.OWNER_ANSWER)) == capture.ANSWER_SESSION_MAX  # the retry stored nothing twice
    assert "5 signal(s) over the per-session cap dropped" in text


def test_each_extractor_keeps_its_own_cap_and_the_report_counts_per_extractor(tmp_path: Path) -> None:
    lifecycle, svc, t = _setup(tmp_path)
    lines = _ask_lines("s1", 0, 3)
    fixed = FIXED * 1
    for i, (command, result, error) in enumerate(fixed):
        call = f"s1-f{i}"
        lines.append(
            {
                "sessionId": "s1",
                "timestamp": "2026-11-18T10:01:00Z",
                "message": {
                    "content": [{"type": "tool_use", "id": call, "name": "Bash", "input": {"command": command}}]
                },
            }
        )
        lines.append(
            {
                "sessionId": "s1",
                "timestamp": "2026-11-18T10:01:01Z",
                "message": {
                    "content": [{"type": "tool_result", "tool_use_id": call, "content": result, "is_error": error}]
                },
            }
        )
    edit = {"type": "tool_use", "id": "s1-e", "name": "Edit", "input": {"file_path": "src/a.py"}}
    lines.append({"sessionId": "s1", "timestamp": "2026-11-18T10:02:00Z", "message": {"content": [edit]}})
    edited = {"type": "tool_result", "tool_use_id": "s1-e", "content": "updated"}
    lines.append({"sessionId": "s1", "timestamp": "2026-11-18T10:02:01Z", "message": {"content": [edited]}})
    _write_session(t, "s1", lines)
    text = lifecycle.on_session_start("startup", session_id="now")
    assert len(_calls(svc, capture.OWNER_ANSWER)) == 3
    assert len(_calls(svc, capture.EXTRACTOR)) == 1
    assert _calls(svc, capture.SESSION_OUTCOME) == [capture.OUTCOME_KEY]
    assert "5 record(s) stored (failed-then-fixed 1, owner-answer 3, session-outcome 1) from 1 session(s)" in text
    outcome = next(m for m in _captured(svc) if f"{CAPTURE_EXTRACTOR_TAG}{capture.SESSION_OUTCOME}" in m.tags)
    assert outcome.type == MemoryType.EPISODE and outcome.tier == MemoryTier.SHORT_TERM
    lifecycle.on_session_start("startup", session_id="now")
    assert len(_captured(svc)) == 5  # committed: nothing stored twice


# ── promotion candidates (D6) and the recall limit (D7; SC-5) ──────────────


def _captured_record(svc: Any, content: str, extractor: str, session: str, call: str, kind: MemoryType) -> str:
    return str(
        svc.retain(
            content,
            kind,
            session_id=session,
            source="capture",
            tags=[
                CAPTURE_ORIGIN_TAG,
                f"{CAPTURE_SESSION_TAG}{session}",
                f"{CAPTURE_CALL_TAG}{call}",
                f"{CAPTURE_EXTRACTOR_TAG}{extractor}",
            ],
            content_dedup=False,
        )
    )


def test_at_most_two_owner_answers_are_promotion_candidates_and_no_other_captured_record(tmp_path: Path) -> None:
    _, svc, _ = _setup(tmp_path)
    answers = [
        _captured_record(svc, f"answer {i}", capture.OWNER_ANSWER, "s1", f"c#{i}", MemoryType.EPISODE) for i in range(4)
    ]
    fixed = _captured_record(svc, "Command `make` failed", capture.EXTRACTOR, "s1", "f", MemoryType.OBSERVATION)
    own = svc.retain("the agent's own note", MemoryType.OBSERVATION)
    for ref in [*answers, fixed]:
        for _ in range(3):
            svc.get(ref)  # recalled often: they would rank above the agent's note
    candidates = [c["ref_id"] for c in svc.consolidate(limit=10)["candidates"]]
    assert sum(ref in candidates for ref in answers) == capture.ANSWER_CANDIDATES == 2
    assert fixed not in candidates and own in candidates


def test_one_recall_result_holds_at_most_three_captured_records_per_origin_session(tmp_path: Path) -> None:
    _, svc, _ = _setup(tmp_path)
    text = "deploys go out on Tuesdays after the release review"
    heavy = [
        _captured_record(svc, f"{text} ({i})", capture.OWNER_ANSWER, "s1", f"c#{i}", MemoryType.EPISODE)
        for i in range(6)
    ]
    other = _captured_record(svc, f"{text} (other session)", capture.OWNER_ANSWER, "s2", "c#0", MemoryType.EPISODE)
    own = svc.retain(f"{text} (agent)", MemoryType.FACT)
    found = [r.ref_id for r in svc.recall(text, top_k=5)]
    assert sum(ref in found for ref in heavy) == 3
    assert other in found and own in found


# ── after the review of #150 (A1–A3) ───────────────────────────────────────


def test_links_of_each_kind_are_capped_then_counted() -> None:
    urls = "\n".join(f"https://github.com/o/r/pull/{n}" for n in range(1, 14))
    (signal,) = capture.extract_outcome(_session(_step("Bash", urls, command="for i in 1..13; gh pr create")))
    assert "opened PR https://github.com/o/r/pull/1, " in signal.content
    assert "https://github.com/o/r/pull/10 (and 3 more)" in signal.content
    assert "pull/11" not in signal.content


@pytest.mark.parametrize(
    ("tool", "tool_input"),
    [
        ("mcp__github__pull_request_review_write", {"method": "create", "owner": "o", "repo": "r", "pullNumber": 5}),
        ("mcp__github__create_pending_pull_request_review", {"owner": "o", "repo": "r", "pullNumber": 5}),
        ("mcp__github__add_issue_comment", {"owner": "o", "repo": "r", "issue_number": 5}),
        ("mcp__github__create_branch", {"owner": "o", "repo": "r", "branch": "b"}),
        ("mcp__github__issue_write", {"method": "update", "owner": "o", "repo": "r", "issue_number": 5}),
    ],
)
def test_reviews_comments_and_other_creates_are_not_outcomes(tool: str, tool_input: dict[str, Any]) -> None:
    """A2: a review carries the PR's URL in its result, but opens nothing."""
    result = json.dumps({"html_url": "https://github.com/o/r/pull/5#pullrequestreview-1"})
    assert capture.extract_outcome(_session(_step(tool, result, tool_input=tool_input))) == []


def test_a_command_that_creates_and_merges_records_both() -> None:
    step = _step("Bash", "https://github.com/o/r/pull/21", command="gh pr create --fill && gh pr merge --auto --squash")
    (signal,) = capture.extract_outcome(_session(step))
    assert "opened PR https://github.com/o/r/pull/21" in signal.content
    assert "merged PR https://github.com/o/r/pull/21" in signal.content


def test_the_two_newest_answers_are_the_candidates_when_they_tie(tmp_path: Path) -> None:
    """A3: captured answers tie on rank; the newest win, not whichever the store lists first."""
    _, svc, _ = _setup(tmp_path)
    refs = [
        _captured_record(svc, f"answer {i}", capture.OWNER_ANSWER, "s1", f"c#{i}", MemoryType.EPISODE) for i in range(4)
    ]
    base = datetime.now(UTC)
    for age, ref in zip((3, 2, 1, 0), refs, strict=True):  # refs[3] is the newest
        svc._vector_store.update_metadata(ref, {"timestamp": (base - timedelta(days=age)).isoformat()})
    candidates = [c["ref_id"] for c in svc.consolidate(limit=10)["candidates"]]
    assert [ref for ref in refs if ref in candidates] == refs[2:]

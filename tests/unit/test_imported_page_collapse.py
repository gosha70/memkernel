# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""Imported-page collapse (specs/memkernel-0-18-imported-page-collapse): the link, the selection, recall, hook blocks
and promotion candidates."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

import chromadb
import pytest

from memkernel.config import MemKernelSettings
from memkernel.core.collapse import collapse
from memkernel.core.models import (
    HASH_SCHEME_CANONICAL,
    HASH_SCHEME_RAW,
    NEEDS_REVIEW_KEY,
    REVIEW_REASON_KEY,
    WIKI_TAG,
    WITHDRAWN_DEPRECATED,
    ArtifactRef,
    Caller,
    MemoryType,
    RecallReceipt,
)
from memkernel.factory import build_service
from memkernel.lifecycle import MemoryLifecycle
from memkernel.memory.dedup import compute_content_hash
from memkernel.wiki.pages import WikiPage
from memkernel.wiki.sync import (
    MEMKERNEL_HASH_SCHEME_KEY,
    MEMKERNEL_REF_KEY,
    MEMKERNEL_SHA256_KEY,
    ImportReport,
    WikiImporter,
)
from tests.conftest import MockEmbedding

if TYPE_CHECKING:
    from pathlib import Path

    from memkernel.core.models import SearchQuery

pytestmark = pytest.mark.unit

SOURCE = "Use Postgres for the user store."
PAGE = "Use Postgres for the user store\n\nBecause of concurrent writes."


def _service(**overrides: Any) -> Any:
    base: dict[str, Any] = {"project_id": f"s5-{uuid.uuid4().hex[:8]}", "chroma_persist_path": ""}
    base.update(overrides)
    return build_service(MemKernelSettings(**base), embedding=MockEmbedding(), chroma_client=chromadb.EphemeralClient())


def _page_memory(svc: Any, source: str | None, content: str = PAGE) -> str:
    """A wiki page's memory, linked to ``source`` as the import links it."""
    ref = svc.retain(content, MemoryType.DECISION, tags=[WIKI_TAG])
    svc.set_wiki_source(ref, source)
    return str(ref)


def _ranked(monkeypatch: pytest.MonkeyPatch, svc: Any, order: list[str]) -> None:
    """The search returns ``order``'s first ``top_k`` records, each scored by its rank (the first highest)."""

    def search(query: SearchQuery) -> list[ArtifactRef]:
        refs = []
        for rank, ref_id in enumerate(order[: query.top_k]):
            memory = svc._vector_store.get_by_id(ref_id)
            refs.append(
                ArtifactRef(
                    ref_id=ref_id,
                    preview=memory.content[:20],
                    score=1.0 - rank / 100,
                    token_count=memory.token_count,
                    type=memory.type,
                    timestamp=memory.timestamp,
                )
            )
        return refs

    monkeypatch.setattr(svc._search_service, "search", search)


def _fillers(svc: Any, count: int) -> list[str]:
    return [svc.retain(f"Filler decision number {i}.", MemoryType.DECISION) for i in range(count)]


# ── FR-003: the selection ─────────────────────────────────────────────────────


def _links(graph: dict[str, list[str]]) -> Any:
    """``paths_of`` over a fixed graph of ancestor links, breadth first, as ancestor_paths walks the store."""

    def paths_of(ref: str) -> dict[str, list[str]]:
        paths: dict[str, list[str]] = {}
        frontier = [[ref]]
        while frontier:
            path = frontier.pop(0)
            for parent in graph.get(path[-1], []):
                if parent != ref and parent not in paths:
                    paths[parent] = [*path, parent]
                    frontier.append(paths[parent])
        return paths

    return paths_of


def test_a_source_ranked_above_its_page_gives_way_and_the_order_is_kept() -> None:
    """Q1: the source at rank 2, its page at rank 4, limit 5: ranks 1, 3, 4 (the page), 5, 6 are shown."""
    shown, hidden = collapse(["a", "src", "b", "page", "c", "d", "e"], 5, _links({"page": ["src"]}))
    assert shown == ["a", "b", "page", "c", "d"]
    assert hidden == [{"ref_id": "src", "by": "page", "path": ["page", "src"]}]


def test_a_descendant_past_the_limit_hides_nothing() -> None:
    shown, hidden = collapse(["src", "a", "b", "c", "d", "page"], 5, _links({"page": ["src"]}))
    assert shown == ["src", "a", "b", "c", "d"] and hidden == []


def test_a_chain_shows_its_highest_ranked_descendant_and_hides_the_rest() -> None:
    """A promoted copy of a page hides the page and the page's source."""
    shown, hidden = collapse(["page", "src", "copy", "a"], 5, _links({"copy": ["page"], "page": ["src"]}))
    assert shown == ["copy", "a"]
    assert hidden == [
        {"ref_id": "src", "by": "copy", "path": ["copy", "page", "src"]},
        {"ref_id": "page", "by": "copy", "path": ["copy", "page"]},
    ]


def test_a_kept_page_removed_by_a_later_copy_keeps_its_source_hidden() -> None:
    """The page hides its source; the copy ranked below removes the page; the source stays hidden by the copy."""
    shown, hidden = collapse(["page", "x", "copy", "src"], 3, _links({"copy": ["page"], "page": ["src"]}))
    assert shown == ["x", "copy"]
    assert [entry["ref_id"] for entry in hidden] == ["src", "page"]


def test_two_pages_of_one_source_hide_it_once() -> None:
    shown, hidden = collapse(["p1", "src", "p2"], 5, _links({"p1": ["src"], "p2": ["src"]}))
    assert shown == ["p1", "p2"]
    assert hidden == [{"ref_id": "src", "by": "p1", "path": ["p1", "src"]}]


def test_an_ancestor_that_was_never_a_candidate_is_not_reported() -> None:
    shown, hidden = collapse(["copy", "a"], 5, _links({"copy": ["page"], "page": ["src"]}))
    assert shown == ["copy", "a"] and hidden == []


# ── FR-002: the reserved tag ──────────────────────────────────────────────────


def test_retain_refuses_the_reserved_tag() -> None:
    """SC-4."""
    svc = _service()
    source = svc.retain(SOURCE, MemoryType.DECISION)
    with pytest.raises(ValueError, match="reserved for the wiki import"):
        svc.retain("A note", MemoryType.FACT, tags=[f"wiki-source:{source}"])


def test_set_wiki_source_adds_replaces_and_removes_the_link() -> None:
    svc = _service()
    first = svc.retain(SOURCE, MemoryType.DECISION)
    second = svc.retain("Use Redis for sessions.", MemoryType.DECISION)
    page = svc.retain(PAGE, MemoryType.DECISION, tags=[WIKI_TAG])

    assert svc.set_wiki_source(page, first) is True
    assert svc.set_wiki_source(page, first) is False  # nothing changed
    assert svc.get(page, touch=False).wiki_source == first
    assert svc.set_wiki_source(page, second) is True
    assert [t for t in svc.get(page, touch=False).tags if t.startswith("wiki-source:")] == [f"wiki-source:{second}"]
    assert svc.set_wiki_source(page, None) is True
    assert svc.get(page, touch=False).wiki_source is None


def test_set_wiki_source_refuses_a_record_that_is_not_a_wiki_memory() -> None:
    svc = _service()
    source = svc.retain(SOURCE, MemoryType.DECISION)
    other = svc.retain("Use Redis for sessions.", MemoryType.DECISION)
    with pytest.raises(ValueError, match="not a wiki memory"):
        svc.set_wiki_source(other, source)
    with pytest.raises(ValueError, match="not a memory in this store"):
        svc.set_wiki_source("missing", source)


def test_promote_leaves_the_link_off_and_the_copy_reaches_the_source_through_the_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    svc = _service()
    source = svc.retain(SOURCE, MemoryType.DECISION)
    page = _page_memory(svc, source)
    copy = svc.promote(page, MemoryType.CONVENTION, content="Postgres holds the user store; never MySQL.")
    promoted = svc.get(copy, touch=False)
    assert promoted.wiki_source is None and promoted.promoted_from == page

    _ranked(monkeypatch, svc, [source, page, copy])
    receipt = RecallReceipt()
    assert [r.ref_id for r in svc.recall("user store", top_k=5, touch=False, receipt=receipt)] == [copy]
    assert receipt.collapsed == [
        {"ref_id": source, "by": copy, "path": [copy, page, source]},
        {"ref_id": page, "by": copy, "path": [copy, page]},
    ]


# ── FR-003, D2: recall ────────────────────────────────────────────────────────


def test_recall_shows_the_page_in_its_own_place_with_its_own_score(monkeypatch: pytest.MonkeyPatch) -> None:
    """Q1 through recall: the source at rank 2, the page at rank 4, top_k 5."""
    svc = _service()
    a, b, c, d, e = _fillers(svc, 5)
    source = svc.retain(SOURCE, MemoryType.DECISION)
    page = _page_memory(svc, source)
    _ranked(monkeypatch, svc, [a, source, b, page, c, d, e])

    receipt = RecallReceipt()
    results = svc.recall("user store", top_k=5, touch=False, receipt=receipt)

    assert [r.ref_id for r in results] == [a, b, page, c, d]
    assert results[2].score == pytest.approx(0.97)  # rank 4's own score, not the source's
    assert receipt.excluded is not None and receipt.excluded["collapsed"] == 1
    assert receipt.collapsed == [{"ref_id": source, "by": page, "path": [page, source]}]
    assert [m.ref_id for m in receipt.memories] == [r.ref_id for r in results]
    assert svc.get(source, touch=False).content == SOURCE  # nothing is edited in the source


@pytest.mark.parametrize("drop", ["flagged", "withdrawn", "past_the_limit"])
def test_the_source_is_shown_when_its_page_is_not(monkeypatch: pytest.MonkeyPatch, drop: str) -> None:
    """SC-3: never both, and never neither."""
    svc = _service()
    fillers = _fillers(svc, 3)
    source = svc.retain(SOURCE, MemoryType.DECISION)
    page = _page_memory(svc, source)
    if drop == "flagged":
        svc._vector_store.update_metadata(page, {NEEDS_REVIEW_KEY: True, REVIEW_REASON_KEY: "changed"})
    elif drop == "withdrawn":
        svc.withdraw(page, WITHDRAWN_DEPRECATED)
    _ranked(monkeypatch, svc, [source, *fillers, page])

    receipt = RecallReceipt()
    results = [r.ref_id for r in svc.recall("user store", top_k=4, touch=False, receipt=receipt)]

    assert source in results and page not in results and receipt.collapsed == []
    assert receipt.excluded is not None and receipt.excluded["collapsed"] == 0


def test_a_wider_window_is_selected_again_from_its_first_candidate(monkeypatch: pytest.MonkeyPatch) -> None:
    """The first window (4) has one live record, the source; the second (8) brings in a promoted copy, which hides
    the source the first window showed. Extending the first selection would have kept the source."""
    svc = _service()
    source = svc.retain(SOURCE, MemoryType.DECISION)
    retired = _fillers(svc, 3)
    for ref in retired:
        svc.withdraw(ref, WITHDRAWN_DEPRECATED)
    copy = svc.promote(source, MemoryType.CONVENTION, content="Postgres holds the user store; never MySQL.")
    later = [svc.retain(f"Later decision {i}.", MemoryType.DECISION) for i in range(3)]
    _ranked(monkeypatch, svc, [source, *retired, copy, *later])

    receipt = RecallReceipt()
    results = [r.ref_id for r in svc.recall("user store", top_k=2, touch=False, receipt=receipt)]

    assert results == [copy, later[0]]
    assert receipt.collapsed == [{"ref_id": source, "by": copy, "path": [copy, source]}]


def test_recall_without_collapse_returns_the_window_unselected(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = _service()
    source = svc.retain(SOURCE, MemoryType.DECISION)
    page = _page_memory(svc, source)
    _ranked(monkeypatch, svc, [source, page])

    receipt = RecallReceipt()
    results = svc.recall("user store", top_k=5, touch=False, receipt=receipt, collapse=False)

    assert [r.ref_id for r in results] == [source, page] and receipt.collapsed == []


# ── Visibility (the owner, before merge) ──────────────────────────────────────


def test_a_published_copy_of_a_private_note_hides_it_only_for_its_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = _service()
    a, b = Caller("agent-a"), Caller("agent-b")
    note = svc.retain("Private: Postgres for the user store.", MemoryType.DECISION, scope="agent", caller=a)
    copy = svc.promote(note, MemoryType.DECISION, scope="project", caller=a)
    _ranked(monkeypatch, svc, [copy, note])

    for_b = RecallReceipt()
    assert [r.ref_id for r in svc.recall("user store", touch=False, receipt=for_b, caller=b)] == [copy]
    assert for_b.collapsed == [] and for_b.excluded is not None and for_b.excluded["collapsed"] == 0
    for_a = RecallReceipt()
    assert [r.ref_id for r in svc.recall("user store", touch=False, receipt=for_a, caller=a)] == [copy]
    assert for_a.collapsed == [{"ref_id": note, "by": copy, "path": [copy, note]}]


def test_a_record_the_caller_cannot_see_ends_the_walk(monkeypatch: pytest.MonkeyPatch) -> None:
    """C -> X -> Y with X private to agent A: for agent B, Y is shown beside C and nothing names X."""
    svc = _service()
    a, b = Caller("agent-a"), Caller("agent-b")
    y = svc.retain(SOURCE, MemoryType.DECISION)
    x = svc.retain("Private: Postgres, checked.", MemoryType.DECISION, promoted_from=y, scope="agent", caller=a)
    c = svc.retain("Postgres holds the user store.", MemoryType.DECISION, promoted_from=x, caller=a)
    _ranked(monkeypatch, svc, [c, x, y])

    for_b = RecallReceipt()
    assert [r.ref_id for r in svc.recall("user store", touch=False, receipt=for_b, caller=b)] == [c, y]
    assert for_b.collapsed == []
    for_a = RecallReceipt()
    assert [r.ref_id for r in svc.recall("user store", touch=False, receipt=for_a, caller=a)] == [c]
    assert for_a.collapsed == [
        {"ref_id": x, "by": c, "path": [c, x]},
        {"ref_id": y, "by": c, "path": [c, x, y]},
    ]


# ── FR-003: hook blocks ───────────────────────────────────────────────────────


def test_the_startup_block_shows_the_page_and_not_its_source() -> None:
    svc = _service()
    source = svc.retain(SOURCE, MemoryType.DECISION)
    page = _page_memory(svc, source)
    text = MemoryLifecycle(svc, svc.settings).on_session_start("startup")
    assert f"({page})" in text and f"({source})" not in text


def test_a_promoted_copy_past_the_blocks_limit_hides_nothing() -> None:
    """The 6th-10th case: the copy ranks below the six shown, so its source stays in the block."""
    svc = _service()
    source = svc.retain(SOURCE, MemoryType.DECISION, importance=0.95)
    _fillers(svc, 6)
    copy = svc.promote(source, MemoryType.FACT, content="Postgres holds the user store.")  # FACT ranks after decisions
    text = MemoryLifecycle(svc, svc.settings).on_session_start("startup")
    assert f"({source})" in text and f"({copy})" not in text


def test_a_hook_block_follows_links_only_through_what_the_processes_caller_can_see() -> None:
    svc_a = _service(agent_id="agent-a")
    note = svc_a.retain("Private: Postgres for the user store.", MemoryType.DECISION, scope="agent")
    copy = svc_a.promote(note, MemoryType.DECISION, content="Postgres holds the user store.", scope="project")
    shown_a, collapsed_a = MemoryLifecycle(svc_a, svc_a.settings)._distinct(
        [svc_a.get(copy, touch=False), svc_a.get(note, touch=False)], None, 6
    )
    assert [m.ref_id for m in shown_a] == [copy]
    assert collapsed_a == [{"ref_id": note, "by": copy, "path": [copy, note]}]

    svc_a.settings.agent_id = "agent-b"  # the same store, read as another agent's process
    shown_b, collapsed_b = MemoryLifecycle(svc_a, svc_a.settings)._distinct(
        [svc_a.get(copy, touch=False, caller=Caller("agent-b"))], None, 6
    )
    assert [m.ref_id for m in shown_b] == [copy] and collapsed_b == []


# ── FR-004: promotion candidates ──────────────────────────────────────────────


def test_a_source_linked_from_a_live_page_is_not_a_promotion_candidate() -> None:
    """SC-6 (D3)."""
    svc = _service()
    source = svc.retain("The user store runs on Postgres.", MemoryType.EPISODE, importance=0.9)
    page = _page_memory(svc, source)

    assert source not in [c["ref_id"] for c in svc.consolidate(limit=10, purge=False)["candidates"]]
    svc.withdraw(page, WITHDRAWN_DEPRECATED)  # a page that is no longer live hides nothing
    assert source in [c["ref_id"] for c in svc.consolidate(limit=10, purge=False)["candidates"]]


# ── FR-001, FR-005: the link at import ────────────────────────────────────────


def _link(svc: Any, tmp_path: Path, extra: dict[str, str]) -> tuple[ImportReport, str]:
    page_ref = svc.retain(PAGE, MemoryType.DECISION, tags=[WIKI_TAG])
    report = ImportReport()
    page = WikiPage(page_type="decision", slug="use-postgres", title="Use Postgres", extra=extra)
    WikiImporter(svc, tmp_path / "wiki")._link_source("decisions/use-postgres.md", page, page_ref, report)
    return report, page_ref


def _exported(memory: Any, **extra: str) -> dict[str, str]:
    return {
        MEMKERNEL_REF_KEY: memory.ref_id,
        MEMKERNEL_SHA256_KEY: memory.content_hash,
        MEMKERNEL_HASH_SCHEME_KEY: memory.hash_scheme,
        **extra,
    }


def test_a_page_that_holds_up_is_linked(tmp_path: Path) -> None:
    svc = _service()
    source = svc.get(svc.retain(SOURCE, MemoryType.DECISION), touch=False)
    report, page_ref = _link(svc, tmp_path, _exported(source))
    assert report.linked == [{"page": "decisions/use-postgres.md", "ref_id": source.ref_id}] and report.unlinked == []
    assert svc.get(page_ref, touch=False).wiki_source == source.ref_id


def test_a_page_exported_before_0_17_links_under_sha256_raw(tmp_path: Path) -> None:
    svc = _service()
    source = svc.retain("  Use Postgres.  ", MemoryType.DECISION)  # raw and canonical hashes differ
    extra = {
        MEMKERNEL_REF_KEY: source,
        MEMKERNEL_SHA256_KEY: compute_content_hash("  Use Postgres.  ", HASH_SCHEME_RAW),
    }
    report, page_ref = _link(svc, tmp_path, extra)
    assert report.linked and svc.get(page_ref, touch=False).wiki_source == source


def test_a_page_without_memkernel_ref_gets_no_link_and_no_entry(tmp_path: Path) -> None:
    svc = _service()
    report, page_ref = _link(svc, tmp_path, {})
    assert report.linked == [] and report.unlinked == [] and svc.get(page_ref, touch=False).wiki_source is None


def _reason(svc: Any, tmp_path: Path, extra: dict[str, str]) -> str:
    report, page_ref = _link(svc, tmp_path, extra)
    assert report.linked == [] and svc.get(page_ref, touch=False).wiki_source is None
    ((entry),) = report.unlinked
    assert entry["page"] == "decisions/use-postgres.md" and entry["ref_id"] == extra[MEMKERNEL_REF_KEY]
    return str(entry["reason"])


@pytest.mark.parametrize("corrects", ["abc123", "not a valid, value!"])
def test_corrects_wins_valid_or_not(tmp_path: Path, corrects: str) -> None:
    svc = _service()
    source = svc.get(svc.retain(SOURCE, MemoryType.DECISION), touch=False)
    assert _reason(svc, tmp_path, _exported(source, corrects=corrects)) == "has_corrects"


def test_each_refused_case_reports_its_reason(tmp_path: Path) -> None:
    """SC-2, in FR-001's order."""
    svc = _service()
    assert _reason(svc, tmp_path, {MEMKERNEL_REF_KEY: "no-such-memory"}) == "not_in_store"
    wiki = svc.get(svc.retain("Another page's text.", MemoryType.DECISION, tags=[WIKI_TAG]), touch=False)
    assert _reason(svc, tmp_path, _exported(wiki)) == "wiki_memory"

    old = svc.get(svc.retain("The user store runs on MySQL.", MemoryType.DECISION), touch=False)
    svc.retain("The user store runs on Postgres 16.", MemoryType.DECISION, supersedes=old.ref_id)
    assert _reason(svc, tmp_path, _exported(old)) == "retired"
    gone = svc.get(svc.retain("Deploys go out on Fridays.", MemoryType.DECISION), touch=False)
    svc.withdraw(gone.ref_id, WITHDRAWN_DEPRECATED)
    assert _reason(svc, tmp_path, _exported(gone)) == "retired"

    for scope in ("agent", "task"):
        private = svc.get(
            svc.retain(f"Private {scope} note.", MemoryType.DECISION, scope=scope, caller=Caller("a", "t")),
            touch=False,
            caller=Caller("a", "t"),
        )
        assert _reason(svc, tmp_path, _exported(private)) == "not_project_scope"

    source = svc.get(svc.retain(SOURCE, MemoryType.DECISION), touch=False)
    assert _reason(svc, tmp_path, {MEMKERNEL_REF_KEY: source.ref_id}) == "no_hash"
    unknown = _exported(source, **{MEMKERNEL_HASH_SCHEME_KEY: "sha512-something"})
    assert _reason(svc, tmp_path, unknown) == "unknown_scheme"
    mismatch = _exported(source, **{MEMKERNEL_SHA256_KEY: compute_content_hash("other", HASH_SCHEME_CANONICAL)})
    assert _reason(svc, tmp_path, mismatch) == "hash_mismatch"


def test_a_check_that_fails_now_removes_a_link_set_earlier(tmp_path: Path) -> None:
    svc = _service()
    source = svc.get(svc.retain(SOURCE, MemoryType.DECISION), touch=False)
    page_ref = svc.retain(PAGE, MemoryType.DECISION, tags=[WIKI_TAG])
    importer = WikiImporter(svc, tmp_path / "wiki")
    rel = "decisions/use-postgres.md"

    importer._link_source(
        rel, WikiPage(page_type="decision", slug="s", title="t", extra=_exported(source)), page_ref, ImportReport()
    )
    assert svc.get(page_ref, touch=False).wiki_source == source.ref_id
    importer._link_source(rel, WikiPage(page_type="decision", slug="s", title="t", extra={}), page_ref, ImportReport())
    assert svc.get(page_ref, touch=False).wiki_source is None

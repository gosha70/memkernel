# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""The governed import against the real wiki-studio (memkernel-0-6 part 2a, FR-010 to FR-017, SC-9).

The curator's side is driven through wiki-studio's API as its own Release B
loop test drives it: a guarded update from draft to stable, then ``approve``.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

import pytest

from memkernel.core.models import MemoryTier, MemoryType
from memkernel.wiki.sync import DEFAULT_PROPOSALS_SUBDIR, WikiExporter, WikiImporter
from tests.unit.test_wiki import NO_EXTRA_ENV, _service

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.integration

try:  # fails, never skips, without wiki-studio, unless MK_TEST_NO_EXTRA=1 marks a deliberate no-extra run
    import wiki_studio.api as api
    from wiki_studio.paths import WikiPaths
    from wiki_studio.proposal import PageEdit
except ImportError:
    if os.environ.get(NO_EXTRA_ENV) == "1":
        pytest.skip("deliberate no-extra run", allow_module_level=True)
    raise

DECISION = "Use Postgres for the user DB\n\nBecause of concurrent writes."
OTHER = "Use arq for background jobs\n\nBecause it is async-native."
WRONG = "Deploys happen on Fridays after 17:00."
ALSO_WRONG = "Deploys need two approvals from the release team."
RIGHT = "Deploys happen on Tuesdays before noon; never on Fridays."


class Wiki:
    """One project: a memkernel store, its wiki and the curator's wiki-studio calls."""

    def __init__(self, root: Path, svc: Any = None) -> None:
        self.root = root
        self.wiki = root / "knowledge" / "wiki"
        self.proposals = root / DEFAULT_PROPOSALS_SUBDIR
        self.paths = WikiPaths.for_root(root, wiki_dir=self.wiki, proposals_dir=self.proposals)
        api.init(self.paths)
        self.svc = svc if svc is not None else _service()
        self._count = 0

    def export(self) -> list[str]:
        report = WikiExporter(self.svc, self.wiki, project_root=self.root, proposals_dir=self.proposals).export()
        assert report.gated, report.gate_error
        return report.written

    def update(self, rel: str, change: Any) -> None:
        page = api.read_page(rel, self.paths)
        self._count += 1
        edit = PageEdit(rel, "update", change(page.text), "curated", page.sha256)
        api.promote(api.propose([edit], self.paths, name=f"curate-{self._count}"), self.paths, by="curator")

    def approve(self, rel: str) -> None:
        api.approve([rel], self.paths, by="curator")

    def publish(self, text: str, memory_type: MemoryType = MemoryType.DECISION) -> tuple[str, str]:
        """Retain, export, mark stable and approve one page; return (page path, the exported memory's ref_id)."""
        ref = self.svc.retain(text, memory_type)
        (rel,) = self.export()
        self.update(rel, lambda text: text.replace("status: draft", "status: stable", 1))
        self.approve(rel)
        return rel, ref

    def import_pages(self) -> Any:
        return WikiImporter(self.svc, self.wiki, project_root=self.root).import_pages()

    def wiki_memories(self, include_superseded: bool = False) -> list[Any]:
        memories = self.svc.list_memories(tier=MemoryTier.LONG_TERM, include_superseded=include_superseded)
        return [m for m in memories if "wiki" in m.tags]


def _correct(rel_text: str, value: str) -> str:
    return rel_text.replace("status: draft", "status: stable", 1).replace(
        "status: stable", f"status: stable\ncorrects: {value}", 1
    )


# ── FR-010, FR-013: approved revisions only ───────────────────────────────────


def test_a_draft_is_not_imported_and_the_report_says_why(tmp_path: Path) -> None:
    w = Wiki(tmp_path)
    w.svc.retain(DECISION, MemoryType.DECISION)
    (rel,) = w.export()

    report = w.import_pages()

    assert report.governed is True and report.imported == [] and w.wiki_memories() == []
    assert {"path": rel, "state": "unapproved", "reason": "draft"} in report.not_approved


def test_a_page_that_declares_itself_approved_is_not_imported(tmp_path: Path) -> None:
    w = Wiki(tmp_path)
    w.svc.retain(DECISION, MemoryType.DECISION)
    (rel,) = w.export()
    page = w.wiki / rel
    page.write_text(page.read_text().replace("status: draft", "status: stable\napproved_by: someone", 1))

    report = w.import_pages()

    assert report.imported == [] and w.wiki_memories() == []
    assert any(entry["path"] == rel and entry["state"] == "unapproved" for entry in report.not_approved)


def test_a_stale_page_keeps_its_last_approved_memory_until_approved_again(tmp_path: Path) -> None:
    w = Wiki(tmp_path)
    rel, _ = w.publish(DECISION)
    assert w.import_pages().imported == [rel]
    page = w.wiki / rel
    page.write_text(page.read_text().replace("concurrent writes", "an unreviewed claim"))

    report = w.import_pages()

    assert report.imported == [] and {"path": rel, "state": "stale", "reason": "live_bytes_differ"} in (
        report.not_approved
    )
    (memory,) = w.wiki_memories()
    assert "an unreviewed claim" not in memory.content
    w.approve(rel)
    assert w.import_pages().imported == [rel]
    (current,) = w.wiki_memories()
    assert "an unreviewed claim" in current.content and current.supersedes == memory.ref_id


def test_bytes_that_change_between_the_check_and_the_read_are_not_imported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    w = Wiki(tmp_path)
    rel, _ = w.publish(DECISION)
    real = api.read_page

    def edited_meanwhile(path: Any, paths: Any) -> Any:  # the page changes after review_state checked it
        (w.wiki / rel).write_text((w.wiki / rel).read_text() + "\nedited after the check\n")
        return real(path, paths)

    monkeypatch.setattr(api, "read_page", edited_meanwhile)
    report = w.import_pages()

    assert report.imported == [] and w.wiki_memories() == []
    assert {"path": rel, "state": "approved", "reason": "live_bytes_differ_from_approved"} in report.not_approved


# ── FR-012: identity and idempotency ──────────────────────────────────────────


def test_importing_twice_adds_nothing(tmp_path: Path) -> None:
    w = Wiki(tmp_path)
    rel, _ = w.publish(DECISION)
    assert w.import_pages().imported == [rel]
    before = w.svc.count()

    again = w.import_pages()

    assert again.imported == [] and again.unchanged == [rel] and again.skipped == [] and w.svc.count() == before
    (memory,) = w.wiki_memories()
    assert any(tag.startswith("page_key:") for tag in memory.tags)
    assert any(tag.startswith("page_sha:") for tag in memory.tags)


def test_a_memory_imported_before_0_6_is_matched_by_its_path(tmp_path: Path) -> None:
    w = Wiki(tmp_path)
    rel, _ = w.publish(DECISION)
    old = w.svc.retain(  # what the pre-0.6 importer wrote: source and slug tags, no page key
        "an older import of this page", MemoryType.DECISION, source=rel, tags=["wiki", "page:old-slug"]
    )

    assert w.import_pages().imported == [rel]

    (current,) = w.wiki_memories()
    assert current.supersedes == old and current.source == rel


def test_a_page_given_a_page_id_keeps_one_live_memory(tmp_path: Path) -> None:
    """wiki-studio's findings prompt curators to add a page_id; the page's key changes, its memory must not double."""
    w = Wiki(tmp_path)
    rel, _ = w.publish(DECISION)
    w.import_pages()
    w.update(
        rel,
        lambda text: text.replace("status: stable", f"status: stable\npage_id: pg-{'a1' * 16}", 1).replace(
            "concurrent writes", "concurrent writes and JSONB"
        ),
    )
    w.approve(rel)

    assert w.import_pages().imported == [rel]

    (current,) = w.wiki_memories()
    assert "JSONB" in current.content and current.supersedes is not None


def test_an_edit_read_without_wiki_studio_after_a_governed_import_keeps_one_live_memory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from memkernel.wiki import sync

    w = Wiki(tmp_path)
    rel, _ = w.publish(DECISION)
    w.import_pages()
    page = w.wiki / rel
    page.write_text(page.read_text().replace("concurrent writes", "concurrent writes and JSONB"))
    monkeypatch.setattr(sync, "gate_available", lambda: None)

    report = w.import_pages()

    assert report.governed is False and rel in report.imported
    (current,) = w.wiki_memories()
    assert "JSONB" in current.content


# ── FR-011: absent, too old, broken ───────────────────────────────────────────


def test_an_installed_wiki_studio_below_the_floor_imports_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from importlib import metadata

    w = Wiki(tmp_path)
    rel, _ = w.publish(DECISION)
    monkeypatch.setattr(metadata, "version", lambda name: "0.6.0")

    report = w.import_pages()

    assert report.import_error is not None and ">= 0.7.0" in report.import_error
    assert report.imported == [] and report.governed is False and w.wiki_memories() == []


def test_a_failing_review_state_imports_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    w = Wiki(tmp_path)
    w.publish(DECISION)

    def broken(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("review state exploded")

    monkeypatch.setattr(api, "review_state", broken)
    report = w.import_pages()

    assert report.import_error is not None and "review state exploded" in report.import_error
    assert report.imported == [] and w.wiki_memories() == []


# ── FR-014, FR-015: corrects ──────────────────────────────────────────────────


def _publish_correction(w: Wiki, value: str) -> str:
    """Export one memory, then approve its page carrying the right text and ``corrects: value``."""
    w.svc.retain(WRONG, MemoryType.CONVENTION)
    (rel,) = w.export()
    w.update(rel, lambda text: _correct(text, value).replace(WRONG, RIGHT))
    w.approve(rel)
    return rel


def test_a_correction_supersedes_the_raw_memories_it_names_and_keeps_them(tmp_path: Path) -> None:
    w = Wiki(tmp_path)
    second = w.svc.retain(ALSO_WRONG, MemoryType.CONVENTION)
    first = w.svc.retain(WRONG, MemoryType.CONVENTION)
    (rel,) = [r for r in w.export() if "fridays" in r]
    w.update(rel, lambda text: _correct(text, f"{first} ,{second}").replace(WRONG, RIGHT))
    w.approve(rel)

    report = w.import_pages()

    assert report.unresolved == [] and report.invalid_corrects == []
    assert sorted(c["ref_id"] for c in report.corrections) == sorted([first, second])
    current = w.svc.list_memories()
    assert not any(WRONG in m.content or ALSO_WRONG in m.content for m in current)
    kept = {m.ref_id: m for m in w.svc.list_memories(include_superseded=True)}
    (page_memory,) = w.wiki_memories()
    assert kept[first].superseded_by == page_memory.ref_id and kept[second].superseded_by == page_memory.ref_id
    assert kept[first].content == WRONG  # the record is kept unchanged: its provenance remains

    again = w.import_pages()
    assert again.corrections == [] and again.unresolved == []  # a second import changes nothing


def test_a_revised_correcting_page_keeps_its_correction_without_reporting_it_unresolved(tmp_path: Path) -> None:
    """The corrected memory stays superseded by the page's earlier memory, now itself replaced: still in effect."""
    w = Wiki(tmp_path)
    w.svc.retain(WRONG, MemoryType.CONVENTION)
    (rel,) = w.export()
    (wrong,) = [m.ref_id for m in w.svc.list_memories() if m.content == WRONG]
    w.update(rel, lambda text: _correct(text, wrong).replace(WRONG, RIGHT))
    w.approve(rel)
    assert [c["ref_id"] for c in w.import_pages().corrections] == [wrong]
    w.update(rel, lambda text: text.replace(RIGHT, RIGHT + " Freeze on release weeks."))
    w.approve(rel)

    report = w.import_pages()

    assert report.imported == [rel] and report.unresolved == [] and report.corrections == []
    assert not any(m.content == WRONG for m in w.svc.list_memories())
    (current,) = w.wiki_memories()
    assert "Freeze on release weeks" in current.content


def test_an_unchanged_page_retries_a_correction_that_could_not_be_applied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A correction left unresolved (here a refused supersede) takes effect on a later import of the same revision."""
    w = Wiki(tmp_path)
    w.svc.retain(WRONG, MemoryType.CONVENTION)
    (rel,) = w.export()
    (wrong,) = [m.ref_id for m in w.svc.list_memories() if m.content == WRONG]
    w.update(rel, lambda text: _correct(text, wrong).replace(WRONG, RIGHT))
    w.approve(rel)
    real = w.svc.supersede

    def refused(ref_id: str, by_ref: str) -> bool:
        raise ValueError("store unavailable")

    monkeypatch.setattr(w.svc, "supersede", refused)
    first = w.import_pages()
    assert first.imported == [rel] and [u["token"] for u in first.unresolved] == [wrong]
    monkeypatch.setattr(w.svc, "supersede", real)

    again = w.import_pages()

    assert again.imported == [] and again.unchanged == [rel]
    assert [c["ref_id"] for c in again.corrections] == [wrong] and again.unresolved == []
    assert not any(m.content == WRONG for m in w.svc.list_memories())


def test_unknown_and_other_project_references_are_reported_not_dropped(tmp_path: Path) -> None:
    other_project = _service()
    foreign = other_project.retain("a memory of another project", MemoryType.FACT)
    w = Wiki(tmp_path)
    rel = _publish_correction(w, f"mem-does-not-exist, {foreign}")

    report = w.import_pages()

    assert report.imported == [rel] and report.corrections == []
    assert {(u["token"], u["reason"]) for u in report.unresolved} == {
        ("mem-does-not-exist", "not a memory in this store"),
        (foreign, "not a memory in this store"),
    }


def test_a_reference_to_a_wiki_memory_is_reported_correct_the_page_instead(tmp_path: Path) -> None:
    w = Wiki(tmp_path)
    other_rel, _ = w.publish(OTHER)
    w.import_pages()
    (wiki_memory,) = [m for m in w.wiki_memories() if m.source == other_rel]
    rel = _publish_correction(w, wiki_memory.ref_id)

    report = w.import_pages()

    assert report.imported == [rel] and report.corrections == []
    assert report.unresolved == [
        {
            "page": rel,
            "token": wiki_memory.ref_id,
            "reason": "a memory imported from the wiki: correct the page instead",
        }
    ]
    assert any(m.ref_id == wiki_memory.ref_id for m in w.wiki_memories())  # still current


@pytest.mark.parametrize(
    ("value", "reason"),
    [("a;b", "has a character other than"), ("a,,b", "an empty token"), ('"a b"', "has a character other than")],
)
def test_an_invalid_corrects_value_imports_the_page_and_applies_nothing(
    tmp_path: Path, value: str, reason: str
) -> None:
    w = Wiki(tmp_path)
    rel = _publish_correction(w, value)

    report = w.import_pages()

    assert report.imported == [rel] and report.corrections == [] and report.unresolved == []
    (entry,) = report.invalid_corrects
    assert entry["page"] == rel and reason in entry["reason"]
    assert any(WRONG in m.content for m in w.svc.list_memories())  # nothing was superseded

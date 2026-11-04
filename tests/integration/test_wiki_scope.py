# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""The wiki import is scoped to its own wiki (memkernel-0-7-wiki-scope, #80), against the real wiki-studio.

SC-1 two wikis, SC-2 legacy memories, SC-3 identity changes, SC-5 the scoped rebuild, SC-7 recovery and D4/D5.
"""

from __future__ import annotations

import json
import os
import shutil
import uuid
from typing import TYPE_CHECKING, Any

import pytest

from memkernel.core.models import WIKI_ID_TAG, WIKI_PATH_TAG, MemoryType
from memkernel.core.services import MemoryService
from memkernel.wiki import ledger as ledger_module
from memkernel.wiki import sync
from memkernel.wiki.ledger import wiki_key
from memkernel.wiki.pages import parse_page
from memkernel.wiki.studio import MANIFEST_FILE
from memkernel.wiki.sync import WikiImporter
from tests.integration.test_wiki_import_governed import DECISION, OTHER, WRONG, Wiki, _correct
from tests.unit.test_wiki import _service

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.integration

CHANGED = "Use Postgres for the user DB\n\nBecause of concurrent writes and JSONB."


def _manifest_id(w: Wiki) -> str:
    return str(json.loads((w.wiki / MANIFEST_FILE).read_text())["wiki_id"])


def _path_tag(w: Wiki, wiki_dir: Path | None = None) -> str:
    return f"{WIKI_PATH_TAG}{wiki_key(None, wiki_dir or w.wiki, w.root)}"


def _live(svc: MemoryService, rel: str) -> list[Any]:
    return [m for m in svc.list_memories() if "wiki" in m.tags and m.source == rel]


def _identity(memory: Any) -> list[str]:
    return sorted(t for t in memory.tags if t.startswith((WIKI_PATH_TAG, WIKI_ID_TAG)))


def _make_legacy(svc: MemoryService, ref: str) -> None:
    """Strip a record's identity tags: what a 0.6 import wrote."""
    memory = svc.get(ref, touch=False)
    assert memory is not None
    svc._vector_store.merge_tags(ref, remove=_identity(memory))


def _owned_duplicate(w: Wiki, rel: str, text: str = "a second record of this page") -> str:
    """A second live record of this wiki for one page (same page key and path), as an earlier defect left."""
    path_hash = wiki_key(None, w.wiki, w.root)
    page = parse_page((w.wiki / rel).read_text(encoding="utf-8"))
    tags = ["wiki", f"page_key:{(page.extra.get('page_id') if page is not None else None) or rel}"]
    return w.svc.retain(text, MemoryType.DECISION, source=rel, tags=tags, wiki_identity=(path_hash, _manifest_id(w)))


# ── SC-1: two wikis, one store ────────────────────────────────────────────────


def _two_wikis(tmp_path: Path) -> tuple[MemoryService, Wiki, Wiki]:
    """One project, one store, two wikis. Each wiki exports from its own scratch service, so a page holds only
    what that wiki published; both import into the shared store."""
    return _service(), Wiki(tmp_path, _service(), "knowledge/a"), Wiki(tmp_path, _service(), "knowledge/b")


def _import(svc: MemoryService, w: Wiki, **adopt: Any) -> Any:
    return WikiImporter(svc, w.wiki, project_root=w.root).import_pages(**adopt)


def _of(svc: MemoryService, w: Wiki, rel: str) -> list[Any]:
    return [m for m in _live(svc, rel) if f"{WIKI_ID_TAG}{_manifest_id(w)}" in m.tags]


def test_two_wikis_with_one_page_path_keep_their_own_records(tmp_path: Path) -> None:
    svc, a, b = _two_wikis(tmp_path)
    rel, _ = a.publish(DECISION)
    assert b.publish(DECISION)[0] == rel  # identical page, same wiki-relative path
    assert _import(svc, a).imported == [rel]
    (mine,) = _of(svc, a, rel)

    assert _import(svc, b).imported == [rel]  # identical bytes: still B's own record, never a dedup into A's

    (theirs,) = _of(svc, b, rel)
    assert theirs.ref_id != mine.ref_id and _identity(theirs) != _identity(mine)
    b.update(rel, lambda t: t.replace("concurrent writes", "concurrent writes and JSONB"))
    b.approve(rel)
    assert _import(svc, b).imported == [rel]
    a_now = svc.get(mine.ref_id, touch=False)
    assert a_now is not None and not a_now.retired() and a_now.tags == mine.tags
    assert _import(svc, a).unchanged == [rel]


def test_two_wikis_sharing_a_page_id_never_cross(tmp_path: Path) -> None:
    svc, a, b = _two_wikis(tmp_path)
    page_id = f"pg-{'b2' * 16}"
    rels = {}
    for w, text in ((a, DECISION), (b, OTHER)):
        rel, _ = w.publish(text)
        w.update(rel, lambda t: t.replace("status: stable", f"status: stable\npage_id: {page_id}", 1))
        w.approve(rel)
        rels[w.wiki] = rel
    _import(svc, a)
    (mine,) = _of(svc, a, rels[a.wiki])

    _import(svc, b)

    assert [m.ref_id for m in _of(svc, a, rels[a.wiki])] == [mine.ref_id] and len(_of(svc, b, rels[b.wiki])) == 1
    assert not svc.get(mine.ref_id, touch=False).retired()  # type: ignore[union-attr]


def test_one_wikis_correction_is_never_anothers(tmp_path: Path) -> None:
    svc, a, b = _two_wikis(tmp_path)
    raw = svc.retain(WRONG, MemoryType.FACT)
    rel, _ = a.publish(DECISION)
    a.update(rel, lambda t: _correct(t, raw))
    a.approve(rel)
    assert _import(svc, a).corrections == [{"page": rel, "ref_id": raw}]
    assert b.publish(DECISION)[0] == rel
    b.update(rel, lambda t: _correct(t, raw))
    b.approve(rel)

    report = _import(svc, b)

    assert report.corrections == [] and [u["token"] for u in report.unresolved] == [raw]


# ── SC-2: legacy memories ─────────────────────────────────────────────────────


def _legacy_store(tmp_path: Path, *texts: str) -> tuple[Wiki, list[str]]:
    """A single-wiki store as 0.6 left it: the pages' memories carry no identity tag."""
    w = Wiki(tmp_path)
    rels = [w.publish(text)[0] for text in texts]
    w.import_pages()
    for rel in rels:
        for memory in _live(w.svc, rel):
            _make_legacy(w.svc, memory.ref_id)
    return w, rels


def test_a_legacy_store_writes_nothing_until_adopted_then_behaves_as_before(tmp_path: Path) -> None:
    w, (rel, other) = _legacy_store(tmp_path, DECISION, OTHER)
    (legacy,) = _live(w.svc, rel)
    w.update(other, lambda t: t.replace("async-native", "async-native and simple"))
    w.approve(other)
    (old_other,) = _live(w.svc, other)

    first = w.import_pages()

    assert first.imported == [] and first.unchanged == []
    assert {e["path"]: e["reason"] for e in first.ambiguous} == {
        rel: "legacy owner unproven",
        other: "legacy owner unproven",
    }
    assert _identity(w.svc.get(legacy.ref_id, touch=False)) == []

    second = w.import_pages(adopt_legacy=True)

    assert second.unchanged == [rel] and second.imported == [other] and second.ambiguous == []
    adopted = w.svc.get(legacy.ref_id, touch=False)
    assert adopted is not None and _identity(adopted) == sorted([_path_tag(w), f"{WIKI_ID_TAG}{_manifest_id(w)}"])
    (new_other,) = _live(w.svc, other)
    assert new_other.supersedes == old_other.ref_id and _identity(new_other) == _identity(adopted)
    third = w.import_pages()
    assert sorted(third.unchanged) == sorted([rel, other]) and third.ambiguous == []


def test_adopt_pages_adopts_exactly_the_named_record(tmp_path: Path) -> None:
    w, (rel, other) = _legacy_store(tmp_path, DECISION, OTHER)
    (legacy,) = _live(w.svc, rel)

    report = w.import_pages(adopt_pages=[{"path": rel, "ref_id": legacy.ref_id}, {"path": "nope.md", "ref_id": "x"}])

    assert report.unchanged == [rel]
    assert {e["path"]: e["reason"] for e in report.ambiguous} == {
        other: "legacy owner unproven",
        "nope.md": "not ambiguous",
    }


def test_a_named_record_that_changed_is_not_adopted(tmp_path: Path) -> None:
    w, (rel,) = _legacy_store(tmp_path, DECISION)
    (legacy,) = _live(w.svc, rel)
    w.svc.forget(legacy.ref_id)
    replacement = w.svc.retain("someone else's page", MemoryType.DECISION, source=rel, tags=["wiki"])

    changed = w.import_pages(adopt_pages=[{"path": rel, "ref_id": legacy.ref_id}])

    assert changed.ambiguous == [{"path": rel, "ref_ids": [replacement], "reason": "candidate changed"}]
    second = w.svc.retain("and a third", MemoryType.DECISION, source=rel, tags=["wiki"])
    several = w.import_pages(adopt_pages=[{"path": rel, "ref_id": replacement}], adopt_legacy=True)
    assert several.ambiguous == [
        {"path": rel, "ref_ids": sorted([replacement, second]), "reason": "several legacy candidates"}
    ]
    assert all(_identity(m) == [] for m in _live(w.svc, rel))


def test_an_owned_record_is_not_blocked_by_a_legacy_one_at_its_path(tmp_path: Path) -> None:
    w = Wiki(tmp_path)
    rel, _ = w.publish(DECISION)
    w.import_pages()
    stray = w.svc.retain("an unrelated legacy record", MemoryType.DECISION, source=rel, tags=["wiki"])
    w.update(rel, lambda t: t.replace("concurrent writes", "concurrent writes and JSONB"))
    w.approve(rel)

    report = w.import_pages()

    assert report.imported == [rel] and report.ambiguous == []
    kept = w.svc.get(stray, touch=False)
    assert kept is not None and not kept.retired() and _identity(kept) == []


def test_ungoverned_legacy_records_are_adopted_the_same_way(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sync, "gate_available", lambda: None)
    wiki = tmp_path / "wiki"
    (wiki / "decisions").mkdir(parents=True)
    rel = "decisions/pg.md"
    (wiki / rel).write_text("---\npage_type: decision\nslug: pg\ntitle: Use Postgres\nstatus: stable\n---\n\nBody.\n")
    svc = _service()
    importer = WikiImporter(svc, wiki, project_root=tmp_path)
    importer.import_pages()
    (memory,) = _live(svc, rel)
    assert _identity(memory) == [f"{WIKI_PATH_TAG}{wiki_key(None, wiki, tmp_path)}"]  # no manifest: path-only
    _make_legacy(svc, memory.ref_id)

    assert importer.import_pages().ambiguous[0]["reason"] == "legacy owner unproven"
    assert importer.import_pages(adopt_legacy=True).imported == [rel]  # deduped into the adopted record
    (adopted,) = _live(svc, rel)
    assert adopted.ref_id == memory.ref_id and _identity(adopted) == [
        f"{WIKI_PATH_TAG}{wiki_key(None, wiki, tmp_path)}"
    ]


def test_duplicate_owned_records_leave_the_page_untouched(tmp_path: Path) -> None:
    w = Wiki(tmp_path)
    rel, _ = w.publish(DECISION)
    w.import_pages()
    (first,) = _live(w.svc, rel)
    second = _owned_duplicate(w, rel)

    current = w.import_pages()  # the page is already current: the early return must not pick one

    assert current.ambiguous == [
        {"path": rel, "ref_ids": sorted([first.ref_id, second]), "reason": "duplicate records"}
    ]
    assert current.unchanged == []
    w.update(rel, lambda t: t.replace("concurrent writes", "concurrent writes and JSONB"))
    w.approve(rel)
    changed = w.import_pages()
    assert changed.imported == [] and changed.ambiguous[0]["reason"] == "duplicate records"
    assert sorted(m.ref_id for m in _live(w.svc, rel)) == sorted([first.ref_id, second])


# ── SC-3: identity changes ────────────────────────────────────────────────────


def test_both_import_paths_derive_one_identity(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    w = Wiki(tmp_path)
    rel, _ = w.publish(DECISION)
    w.import_pages()
    (governed,) = _live(w.svc, rel)
    monkeypatch.setattr(sync, "gate_available", lambda: None)

    assert w.import_pages().imported == [rel]  # ungoverned: deduped into the same record

    (ungoverned,) = _live(w.svc, rel)
    assert ungoverned.ref_id == governed.ref_id and _identity(ungoverned) == _identity(governed)


@pytest.mark.parametrize(
    "manifest",
    [
        "symlink",
        "[1, 2]",
        json.dumps({"manifest_version": 2, "wiki_id": str(uuid.uuid4())}),
        '{"manifest_version": 1, "wiki_id": "not-a-uuid"}',
        b"\xff\xfe",
    ],
)
def test_a_manifest_that_fails_identity_validation_stops_the_ungoverned_import(
    manifest: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sync, "gate_available", lambda: None)
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    target = wiki / MANIFEST_FILE
    if manifest == "symlink":
        real = tmp_path / "real.json"
        real.write_text(json.dumps({"manifest_version": 1, "wiki_id": str(uuid.uuid4())}))
        os.symlink(real, target)
    elif isinstance(manifest, bytes):
        target.write_bytes(manifest)
    else:
        target.write_text(manifest)
    svc = _service()

    report = WikiImporter(svc, wiki, project_root=tmp_path).import_pages()

    assert report.import_error is not None and svc.count() == 0


def test_a_newer_manifest_stops_the_governed_import(tmp_path: Path) -> None:
    w = Wiki(tmp_path)
    w.publish(DECISION)
    path = w.wiki / MANIFEST_FILE
    path.write_text(path.read_text().replace('"manifest_version": 1', '"manifest_version": 2'))

    report = w.import_pages()

    assert report.import_error is not None and [m for m in w.wiki_memories()] == []


def _before_the_manifest(w: Wiki, monkeypatch: pytest.MonkeyPatch) -> tuple[str, str]:
    """A wiki imported before it had a manifest: ungoverned imports wrote path-only memories, and a governed run
    without the manifest (which approves nothing) left a path-keyed ledger. Returns (page, the saved manifest)."""
    rel, _ = w.publish(DECISION)
    manifest = w.wiki / MANIFEST_FILE
    saved = manifest.read_text()
    manifest.unlink()
    with monkeypatch.context() as patch:
        patch.setattr(sync, "gate_available", lambda: None)
        assert w.import_pages().imported == [rel]
    assert w.import_pages().not_approved  # governed, no manifest: nothing approved, but the ledger exists
    return rel, saved


def test_a_manifest_added_needs_adopt_manifest_and_moves_the_ledger(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    w = Wiki(tmp_path)
    rel, saved = _before_the_manifest(w, monkeypatch)
    (memory,) = _live(w.svc, rel)
    assert _identity(memory) == [_path_tag(w)]
    path_key = (w.svc.project_id, wiki_key(None, w.wiki, w.root))
    assert path_key in ledger_module._MEMORY_LEDGERS
    (w.wiki / MANIFEST_FILE).write_text(saved)

    refused = w.import_pages(adopt_pages=[{"path": rel, "ref_id": memory.ref_id}])

    assert refused.import_error is not None and "adopt_manifest" in refused.import_error
    assert _identity(w.svc.get(memory.ref_id, touch=False)) == [_path_tag(w)]
    adopted = w.import_pages(adopt_manifest=True)
    assert adopted.import_error is None and adopted.imported == [rel]  # deduped into the adopted record
    assert [m.ref_id for m in _live(w.svc, rel)] == [memory.ref_id]
    assert _identity(w.svc.get(memory.ref_id, touch=False)) == sorted([_path_tag(w), f"{WIKI_ID_TAG}{_manifest_id(w)}"])
    assert path_key not in ledger_module._MEMORY_LEDGERS
    assert (w.svc.project_id, _manifest_id(w)) in ledger_module._MEMORY_LEDGERS


def test_both_ledgers_stop_the_migration_and_a_crash_after_the_rename_is_finished(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    w = Wiki(tmp_path)
    rel, saved = _before_the_manifest(w, monkeypatch)
    (w.wiki / MANIFEST_FILE).write_text(saved)
    id_key = (w.svc.project_id, _manifest_id(w))
    ledger_module._MEMORY_LEDGERS[id_key] = {}  # add, remove, re-add: both ledgers exist

    both = w.import_pages(adopt_manifest=True)

    assert both.import_error is not None and "both" in both.import_error
    (memory,) = _live(w.svc, rel)
    assert _identity(memory) == [_path_tag(w)]
    path_key = (w.svc.project_id, wiki_key(None, w.wiki, w.root))
    ledger_module._MEMORY_LEDGERS[id_key] = ledger_module._MEMORY_LEDGERS.pop(path_key)  # the rename, then a crash
    assert w.import_pages().import_error is not None  # path-only memories remain: still needs adopt_manifest
    assert w.import_pages(adopt_manifest=True).import_error is None
    assert f"{WIKI_ID_TAG}{_manifest_id(w)}" in w.svc.get(memory.ref_id, touch=False).tags  # type: ignore[union-attr]


def test_a_failed_ledger_rename_writes_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state = tmp_path / "state"
    w = Wiki(tmp_path, _service(chroma_persist_path=str(tmp_path / "chroma"), state_dir=str(state)))
    rel, saved = _before_the_manifest(w, monkeypatch)
    (w.wiki / MANIFEST_FILE).write_text(saved)
    files = sorted(p.name for p in (state / "wiki-sync" / w.svc.project_id).glob("*.json"))

    def failing(*args: Any) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(ledger_module.os, "rename", failing)
    report = w.import_pages(adopt_manifest=True)

    assert report.import_error is not None and "disk full" in report.import_error
    assert sorted(p.name for p in (state / "wiki-sync" / w.svc.project_id).glob("*.json")) == files
    assert all(_identity(m) == [_path_tag(w)] for m in _live(w.svc, rel))


@pytest.mark.parametrize("change", ["removed", "replaced"])
def test_a_removed_or_replaced_manifest_stops_the_import(change: str, tmp_path: Path) -> None:
    w = Wiki(tmp_path)
    rel, _ = w.publish(DECISION)
    w.import_pages()
    old_id = _manifest_id(w)
    manifest = w.wiki / MANIFEST_FILE
    if change == "removed":
        manifest.unlink()
    else:
        manifest.write_text(manifest.read_text().replace(old_id, str(uuid.uuid4())))
    (before,) = _live(w.svc, rel)

    report = w.import_pages()

    assert report.import_error is not None and old_id in report.import_error and "restore" in report.import_error
    (after,) = _live(w.svc, rel)
    assert after.tags == before.tags


def test_a_moved_wiki_keeps_its_memories_and_frees_its_old_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    w = Wiki(tmp_path)
    rel, _ = w.publish(DECISION)
    w.import_pages()
    (memory,) = _live(w.svc, rel)
    old_path_tag, wid = _path_tag(w), _manifest_id(w)
    moved = tmp_path / "docs" / "wiki"
    moved.parent.mkdir()
    shutil.move(str(w.wiki), str(moved))
    new_path_tag = _path_tag(w, moved)

    # Before the moved wiki is imported from its new place, a new wiki at the old path is stopped.
    monkeypatch.setattr(sync, "gate_available", lambda: None)
    reuse = tmp_path / "knowledge" / "wiki"
    (reuse / "decisions").mkdir(parents=True)
    (reuse / rel).write_text(
        "---\npage_type: decision\nslug: x\ntitle: Use Postgres for the user DB\nstatus: stable\n---\n\n"
        "Because of concurrent writes.\n"
    )
    stored = w.svc.count()
    blocked = WikiImporter(w.svc, reuse, project_root=tmp_path).import_pages()
    assert blocked.import_error is not None and wid in blocked.import_error and w.svc.count() == stored
    monkeypatch.undo()

    report = WikiImporter(w.svc, moved, project_root=tmp_path).import_pages()

    assert report.unchanged == [rel]
    retagged = w.svc.get(memory.ref_id, touch=False)
    assert retagged is not None and new_path_tag in retagged.tags and old_path_tag not in retagged.tags

    monkeypatch.setattr(sync, "gate_available", lambda: None)
    reused = WikiImporter(w.svc, reuse, project_root=tmp_path).import_pages()
    assert reused.import_error is None and reused.imported == [rel]
    assert w.svc.get(memory.ref_id, touch=False).tags == retagged.tags  # type: ignore[union-attr]
    assert len(_live(w.svc, rel)) == 2  # identical text, two wikis: two records


# ── SC-5: the scoped rebuild ──────────────────────────────────────────────────


def test_a_corrupt_ledger_is_rebuilt_from_this_wikis_memories_only(tmp_path: Path) -> None:
    state = tmp_path / "state"
    svc = _service(chroma_persist_path=str(tmp_path / "chroma"), state_dir=str(state))
    a, b = Wiki(tmp_path, _service(), "knowledge/a"), Wiki(tmp_path, _service(), "knowledge/b")
    a.publish(DECISION)
    b.publish(OTHER)
    _import(svc, a)
    _import(svc, b)
    legacy = svc.retain("a legacy page memory", MemoryType.DECISION, source="x.md", tags=["wiki", "page_key:x.md"])
    ledger_file = state / "wiki-sync" / svc.project_id / f"{_manifest_id(a)}.json"
    ledger_file.write_text("not json")

    report = _import(svc, a)

    assert report.ledger_error is not None
    entries = json.loads(ledger_file.read_text())["entries"]
    owned = {m.ref_id for m in svc.list_memories() if f"{WIKI_ID_TAG}{_manifest_id(a)}" in m.tags}
    assert {e["ref_id"] for e in entries.values()} == owned and legacy not in owned and len(owned) == 1


# ── SC-7: recovery, and D4/D5 duplicates ──────────────────────────────────────


@pytest.mark.parametrize("governed", [True, False])
def test_an_interrupted_supersession_is_completed_by_the_next_import(
    governed: bool, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    w = Wiki(tmp_path)
    rel, _ = w.publish(DECISION)
    if not governed:
        monkeypatch.setattr(sync, "gate_available", lambda: None)
    w.import_pages()
    (old,) = _live(w.svc, rel)
    w.update(rel, lambda t: t.replace("concurrent writes", "concurrent writes and JSONB"))
    w.approve(rel)
    real = MemoryService._mark_superseded

    def crash(self: MemoryService, target: str, by: str) -> None:
        raise OSError("crashed after writing the replacement")

    monkeypatch.setattr(MemoryService, "_mark_superseded", crash)
    if governed:
        assert w.import_pages().sync_failed
    else:
        with pytest.raises(OSError, match="crashed"):
            w.import_pages()
    assert len(_live(w.svc, rel)) == 2  # replacement written, predecessor not yet marked
    monkeypatch.setattr(MemoryService, "_mark_superseded", real)

    report = w.import_pages()

    assert report.ambiguous == []
    (current,) = _live(w.svc, rel)
    assert current.supersedes == old.ref_id
    assert w.svc.get(old.ref_id, touch=False).superseded_by == current.ref_id  # type: ignore[union-attr]


def test_duplicate_predecessors_successors_and_deprecated_pages_are_untouched(tmp_path: Path) -> None:
    w = Wiki(tmp_path)
    a, _ = w.publish(DECISION)
    b, _ = w.publish(OTHER)
    w.import_pages()
    dup_b = _owned_duplicate(w, b, "a second record of the successor")
    w.update(a, lambda t: t.replace("status: stable", f"status: stable\nsuperseded_by: {b}", 1))
    (old_a,) = _live(w.svc, a)

    successor = w.import_pages()

    assert {e["path"] for e in successor.ambiguous} == {b} and successor.superseded == [] and successor.pending == []
    assert not w.svc.get(old_a.ref_id, touch=False).retired()  # type: ignore[union-attr]
    w.svc.forget(dup_b)
    _owned_duplicate(w, a, "a second record of the predecessor")
    predecessor = w.import_pages()
    assert {e["path"] for e in predecessor.ambiguous} == {a} and predecessor.superseded == []

    c, _ = w.publish(WRONG, MemoryType.FACT)
    w.import_pages()
    _owned_duplicate(w, c, "a second record of the deprecated page")
    w.update(c, lambda t: t.replace("status: stable", "status: deprecated", 1))
    w.approve(c)
    deprecated = w.import_pages()
    assert c in {e["path"] for e in deprecated.ambiguous} and deprecated.withdrawn == []
    assert all(not m.retired() for m in _live(w.svc, c))


# ── SC-3 (continued): edits after a move; an interrupted retag ────────────────


def _move(w: Wiki, to: Path) -> None:
    from wiki_studio.paths import WikiPaths

    to.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(w.wiki), str(to))
    w.wiki = to
    w.paths = WikiPaths.for_root(w.root, wiki_dir=to, proposals_dir=w.proposals)


def test_after_a_move_edits_dedup_into_or_supersede_the_wikis_own_record(tmp_path: Path) -> None:
    w = Wiki(tmp_path)
    rel, _ = w.publish(DECISION)
    w.import_pages()
    (memory,) = _live(w.svc, rel)
    _move(w, tmp_path / "docs" / "wiki")
    w.update(rel, lambda t: t.replace("status: stable", "status: stable\nowner: platform", 1))  # frontmatter only
    w.approve(rel)

    assert w.import_pages().imported == [rel]

    (same,) = _live(w.svc, rel)
    assert same.ref_id == memory.ref_id
    assert _identity(same) == sorted([_path_tag(w), f"{WIKI_ID_TAG}{_manifest_id(w)}"])
    w.update(rel, lambda t: t.replace("concurrent writes", "concurrent writes and JSONB"))
    w.approve(rel)
    assert w.import_pages().imported == [rel]
    (new,) = _live(w.svc, rel)
    assert new.supersedes == memory.ref_id and _identity(new) == _identity(same)


def test_a_retag_interrupted_halfway_is_finished_by_the_next_import(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    w = Wiki(tmp_path)
    w.publish(DECISION)
    w.publish(OTHER)
    w.import_pages()
    _move(w, tmp_path / "docs" / "wiki")
    real = MemoryService.set_wiki_identity
    calls: list[str] = []

    def once_then_crash(self: MemoryService, ref_id: str, **kwargs: Any) -> bool:
        calls.append(ref_id)
        if len(calls) == 2:
            raise OSError("crashed halfway through the retag")
        return real(self, ref_id, **kwargs)

    monkeypatch.setattr(MemoryService, "set_wiki_identity", once_then_crash)
    with pytest.raises(OSError, match="halfway"):
        w.import_pages()
    assert sorted(_path_tag(w) in m.tags for m in w.wiki_memories()) == [False, True]
    monkeypatch.setattr(MemoryService, "set_wiki_identity", real)

    report = w.import_pages()

    assert report.import_error is None and len(report.unchanged) == 2
    assert all(_identity(m) == sorted([_path_tag(w), f"{WIKI_ID_TAG}{_manifest_id(w)}"]) for m in w.wiki_memories())


# ── SC-8 (in one process): ordinary retain, promote, without fcntl ────────────


def test_an_agents_identical_text_does_not_touch_the_wiki_memory(tmp_path: Path) -> None:
    w = Wiki(tmp_path)
    rel, _ = w.publish(DECISION)
    w.import_pages()
    (memory,) = _live(w.svc, rel)
    content = memory.content

    own = w.svc.retain(content, MemoryType.DECISION, source=rel, tags=["agent"])

    assert own != memory.ref_id
    assert w.svc.get(memory.ref_id, touch=False).tags == memory.tags  # type: ignore[union-attr]
    report = w.import_pages()
    assert report.unchanged == [rel] and report.ambiguous == []


def test_a_promoted_wiki_memory_never_becomes_a_page_candidate(tmp_path: Path) -> None:
    w = Wiki(tmp_path)
    rel, _ = w.publish(DECISION)
    w.import_pages()
    (memory,) = _live(w.svc, rel)

    copy = w.svc.promote(memory.ref_id, MemoryType.FACT)

    promoted = w.svc.get(copy, touch=False)  # type: ignore[arg-type]
    assert promoted is not None and "wiki" not in promoted.tags and _identity(promoted) == []
    report = w.import_pages()
    assert report.unchanged == [rel] and report.ambiguous == []
    assert w.svc.get(copy, touch=False).tags == promoted.tags  # type: ignore[arg-type, union-attr]


def test_without_fcntl_every_import_runs_unlocked_with_one_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    import logging

    from memkernel.storage import chroma

    monkeypatch.setattr(chroma, "fcntl", None)
    monkeypatch.setattr(chroma, "_unlocked_warned", set())
    w, (rel,) = _legacy_store_persisted(tmp_path, DECISION)
    (legacy,) = _live(w.svc, rel)
    with caplog.at_level(logging.WARNING, logger=chroma.__name__):
        assert w.import_pages(adopt_pages=[{"path": rel, "ref_id": legacy.ref_id}]).unchanged == [rel]
        assert w.import_pages(adopt_legacy=True, adopt_manifest=True).unchanged == [rel]
        _move(w, tmp_path / "docs" / "wiki")
        assert w.import_pages().unchanged == [rel]
    assert _identity(w.svc.get(legacy.ref_id, touch=False)) == sorted([_path_tag(w), f"{WIKI_ID_TAG}{_manifest_id(w)}"])
    warned = [r.getMessage() for r in caplog.records if "runs unlocked" in r.getMessage()]
    assert len(warned) == len(set(warned)) >= 1  # one warning per lock name


def _persisted_service(tmp_path: Path) -> MemoryService:
    """A service on a real persistent store (the shared ``_service`` helper always injects an in-memory client)."""
    from memkernel.config import MemKernelSettings
    from memkernel.retrieval.search import HybridSearchService
    from memkernel.retrieval.sparse import BM25Index
    from memkernel.storage.chroma import ChromaVectorStore
    from tests.conftest import MockEmbedding

    settings = MemKernelSettings(
        project_id=f"scope-{uuid.uuid4().hex[:8]}",
        chroma_persist_path=str(tmp_path / "chroma"),
        state_dir=str(tmp_path / "state"),
    )
    store, sparse = ChromaVectorStore(settings), BM25Index()
    return MemoryService(
        store, MockEmbedding(), sparse, HybridSearchService(store, MockEmbedding(), sparse, settings), settings
    )


def _legacy_store_persisted(tmp_path: Path, *texts: str) -> tuple[Wiki, list[str]]:
    svc = _persisted_service(tmp_path)
    w = Wiki(tmp_path, svc)
    rels = [w.publish(text)[0] for text in texts]
    w.import_pages()
    for rel in rels:
        for memory in _live(w.svc, rel):
            _make_legacy(w.svc, memory.ref_id)
    return w, rels

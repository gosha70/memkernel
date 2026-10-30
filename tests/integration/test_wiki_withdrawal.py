# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""Withdrawal and the sync ledger in the governed wiki import, against the real wiki-studio (memkernel-0-7).

SC-1 deletion, SC-2 deprecation, SC-3 supersession, SC-4 retry and the ledger, SC-6 corrections kept.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest

from memkernel.core.models import WITHDRAWN_DELETED, WITHDRAWN_DEPRECATED, WITHDRAWN_SUPERSEDED, MemoryType
from memkernel.wiki import ledger as ledger_module
from tests.integration.test_wiki_import_governed import DECISION, OTHER, RIGHT, WRONG, Wiki, _correct
from tests.unit.test_wiki import _service

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.integration


def _live_refs(w: Wiki) -> set[str]:
    return {m.ref_id for m in w.wiki_memories()}


def _memory_of(w: Wiki, rel: str) -> Any:
    (memory,) = [m for m in w.wiki_memories(include_superseded=True) if m.source == rel and not m.superseded_by]
    return memory


def _live_of(w: Wiki, rel: str) -> list[Any]:
    return [m for m in w.wiki_memories() if m.source == rel]


# ── SC-1: deletion ────────────────────────────────────────────────────────────


def test_a_deleted_page_withdraws_the_memory_the_ledger_recorded(tmp_path: Path) -> None:
    w = Wiki(tmp_path)
    rel, _ = w.publish(DECISION)
    assert w.import_pages().imported == [rel]
    (memory,) = _live_of(w, rel)
    (w.wiki / rel).unlink()

    report = w.import_pages()

    assert report.withdrawn == [{"path": rel, "ref_id": memory.ref_id, "reason": WITHDRAWN_DELETED}]
    assert _live_of(w, rel) == [] and memory.ref_id not in {r.ref_id for r in w.svc.recall("Postgres", touch=False)}
    kept = w.svc.get(memory.ref_id, touch=False)
    assert kept is not None and kept.withdrawn_reason == WITHDRAWN_DELETED and kept.content == memory.content
    assert w.import_pages().withdrawn == []  # idempotent


def test_a_legacy_memory_is_never_withdrawn_as_deleted(tmp_path: Path) -> None:
    """D3: a memory the ledger did not record as imported (here, imported before the ledger existed and later
    only found current) is not proof of this wiki; deleting its page withdraws nothing."""
    w = Wiki(tmp_path)
    rel, _ = w.publish(DECISION)
    w.import_pages()
    ledger_module._MEMORY_LEDGERS.clear()  # as if the memory was imported before 0.7's ledger
    assert w.import_pages().unchanged == [rel]
    (w.wiki / rel).unlink()

    report = w.import_pages()

    assert report.withdrawn == [] and len(_live_of(w, rel)) == 1


def test_a_listing_error_withdraws_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from memkernel.wiki import sync
    from memkernel.wiki.studio import GateError

    w = Wiki(tmp_path)
    rel, _ = w.publish(DECISION)
    w.import_pages()
    (w.wiki / rel).unlink()

    def failing(*args: Any, **kwargs: Any) -> Any:
        raise GateError("wiki-studio review state failed: boom")

    monkeypatch.setattr(sync, "review_pages", failing)
    report = w.import_pages()

    assert report.import_error is not None and report.withdrawn == [] and len(_live_of(w, rel)) == 1


def test_a_page_still_on_disk_but_unlisted_is_not_deleted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """D3: all three conditions must hold; the file being present is enough to keep the memory."""
    from memkernel.wiki import sync

    w = Wiki(tmp_path)
    rel, _ = w.publish(DECISION)
    w.import_pages()
    real = sync.review_pages
    monkeypatch.setattr(sync, "review_pages", lambda *a, **k: [r for r in real(*a, **k) if r.path != rel])

    assert w.import_pages().withdrawn == [] and len(_live_of(w, rel)) == 1


# ── SC-2: deprecation ─────────────────────────────────────────────────────────


def test_deprecation_withdraws_only_once_approved_and_a_restored_page_gets_a_new_memory(tmp_path: Path) -> None:
    w = Wiki(tmp_path)
    rel, _ = w.publish(DECISION)
    w.import_pages()
    (memory,) = _live_of(w, rel)
    w.update(rel, lambda t: t.replace("status: stable", "status: deprecated", 1))

    assert w.import_pages().withdrawn == [] and _live_of(w, rel) == [memory]  # stale: last approved stays

    w.approve(rel)
    report = w.import_pages()

    assert report.withdrawn == [{"path": rel, "ref_id": memory.ref_id, "reason": WITHDRAWN_DEPRECATED}]
    assert rel not in report.skipped and _live_of(w, rel) == []
    w.update(rel, lambda t: t.replace("status: deprecated", "status: stable", 1))
    w.approve(rel)

    assert w.import_pages().imported == [rel]
    (restored,) = _live_of(w, rel)
    assert restored.ref_id != memory.ref_id


# ── SC-3: supersession ────────────────────────────────────────────────────────


def test_a_superseded_page_is_replaced_by_its_successors_memory(tmp_path: Path) -> None:
    w = Wiki(tmp_path)
    a, _ = w.publish(DECISION)
    b, _ = w.publish(OTHER)
    w.import_pages()
    (old,) = _live_of(w, a)
    (new,) = _live_of(w, b)
    w.update(a, lambda t: t.replace("status: stable", f"status: stable\nsuperseded_by: {b}", 1))

    report = w.import_pages()

    assert report.superseded == [{"path": a, "ref_id": old.ref_id, "by": new.ref_id}]
    stored = w.svc.get(old.ref_id, touch=False)
    assert stored is not None and stored.superseded_by == new.ref_id and stored.withdrawn_reason is None
    assert w.import_pages().superseded == []  # idempotent


def test_a_successor_without_a_memory_is_pending_then_linked_keeping_both_markers(tmp_path: Path) -> None:
    w = Wiki(tmp_path)
    a, _ = w.publish(DECISION)
    w.import_pages()
    (old,) = _live_of(w, a)
    w.svc.retain(OTHER, MemoryType.DECISION)
    (b,) = w.export()  # a draft: no memory yet
    w.update(a, lambda t: t.replace("status: stable", f"status: stable\nsuperseded_by: {b}", 1))

    first = w.import_pages()

    assert [p["path"] for p in first.pending] == [a] and b in first.pending[0]["detail"]
    held = w.svc.get(old.ref_id, touch=False)
    assert held is not None and held.withdrawn_reason == WITHDRAWN_SUPERSEDED and held.superseded_by is None
    w.update(b, lambda t: t.replace("status: draft", "status: stable", 1))
    w.approve(b)

    second = w.import_pages()

    (new,) = _live_of(w, b)
    assert second.superseded == [{"path": a, "ref_id": old.ref_id, "by": new.ref_id}] and second.pending == []
    linked = w.svc.get(old.ref_id, touch=False)
    assert linked is not None and linked.superseded_by == new.ref_id
    assert linked.withdrawn_reason == WITHDRAWN_SUPERSEDED  # both markers: why it left, what replaced it


# ── SC-4: retry and the ledger ────────────────────────────────────────────────


def test_a_failed_withdrawal_is_recorded_and_completed_by_the_next_import(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    w = Wiki(tmp_path)
    rel, _ = w.publish(DECISION)
    w.import_pages()
    (memory,) = _live_of(w, rel)
    (w.wiki / rel).unlink()
    real = w.svc.withdraw

    def failing(*args: Any, **kwargs: Any) -> bool:
        raise OSError("disk full")

    monkeypatch.setattr(w.svc, "withdraw", failing)
    first = w.import_pages()
    monkeypatch.setattr(w.svc, "withdraw", real)

    assert first.sync_failed == [{"path": rel, "action": "withdraw", "error": "disk full", "attempts": 1}]
    assert _live_of(w, rel) == [memory]

    second = w.import_pages()

    assert second.withdrawn == [{"path": rel, "ref_id": memory.ref_id, "reason": WITHDRAWN_DELETED}]
    assert second.sync_failed == [] and _live_of(w, rel) == []


def _persisted(tmp_path: Path) -> Wiki:
    """A service whose settings persist (so the ledger is a file), over an in-memory Chroma client."""
    return Wiki(tmp_path, _service(chroma_persist_path=str(tmp_path / "chroma"), state_dir=str(tmp_path / "state")))


def test_the_ledger_is_one_file_per_project_and_wiki_named_by_the_manifest(tmp_path: Path) -> None:
    from wiki_studio import api

    w = _persisted(tmp_path)
    rel, _ = w.publish(DECISION)
    w.import_pages()
    wiki_id = api.info(w.paths).manifest.wiki_id
    path = tmp_path / "state" / "wiki-sync" / w.svc.project_id / f"{wiki_id}.json"

    entries = json.loads(path.read_text(encoding="utf-8"))["entries"]

    (entry,) = entries.values()
    assert entry["path"] == rel and entry["state"] == "applied" and entry["action"] == "import"
    assert entry["origin"] == "import" and entry["ref_id"] == _live_of(w, rel)[0].ref_id


def test_a_corrupt_ledger_is_reported_kept_aside_and_rebuilt_without_deletion_proof(tmp_path: Path) -> None:
    from wiki_studio import api

    w = _persisted(tmp_path)
    rel, _ = w.publish(DECISION)
    w.import_pages()
    path = tmp_path / "state" / "wiki-sync" / w.svc.project_id / f"{api.info(w.paths).manifest.wiki_id}.json"
    path.write_text("{not json", encoding="utf-8")

    report = w.import_pages()

    assert report.ledger_error is not None and "rebuilt" in report.ledger_error
    assert list(path.parent.glob(f"{path.name}.corrupt-*")) != []
    (entry,) = json.loads(path.read_text(encoding="utf-8"))["entries"].values()
    assert entry["origin"] == "rebuilt"
    (w.wiki / rel).unlink()
    assert w.import_pages().withdrawn == []  # rebuilt entries are not proof the memory came from this wiki


# ── SC-6: corrections stay in effect ──────────────────────────────────────────


def test_withdrawing_a_correcting_page_leaves_its_corrections_in_effect(tmp_path: Path) -> None:
    w = Wiki(tmp_path)
    rel, _ = w.publish(DECISION)
    wrong = w.svc.retain(WRONG, MemoryType.CONVENTION)
    w.update(rel, lambda t: _correct(t, wrong).replace("concurrent writes", RIGHT))
    w.approve(rel)
    w.import_pages()
    w.update(rel, lambda t: t.replace("status: stable", "status: deprecated", 1))
    w.approve(rel)

    report = w.import_pages()

    assert [x["reason"] for x in report.withdrawn] == [WITHDRAWN_DEPRECATED]
    corrected = w.svc.get(wrong, touch=False)
    assert corrected is not None and corrected.superseded_by is not None
    assert wrong not in {m.ref_id for m in w.svc.list_memories()}


def test_a_rename_that_kept_its_page_id_is_not_a_deletion(tmp_path: Path) -> None:
    """D3: matched by page key, the renamed page is the same page; its memory is never withdrawn as deleted."""
    import uuid

    w = Wiki(tmp_path)
    rel, _ = w.publish(DECISION)
    page_id = f"pg-{uuid.uuid4().hex}"
    w.update(rel, lambda t: t.replace("status: stable", f"status: stable\npage_id: {page_id}", 1))
    w.approve(rel)
    w.import_pages()
    renamed = rel.replace(".md", "-renamed.md")
    (w.wiki / renamed).write_bytes((w.wiki / rel).read_bytes())
    (w.wiki / rel).unlink()

    report = w.import_pages()

    assert report.withdrawn == []
    assert any(m.source == rel for m in w.wiki_memories())  # the page's memory is still live


# ── Review of #78 ─────────────────────────────────────────────────────────────


def test_an_unreadable_manifest_stops_the_governed_import(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The ledger key falls back to the path hash only without a manifest or wiki_id; an existing manifest that
    cannot be read stops the import with import_error, before anything is imported or a ledger is touched."""
    from wiki_studio import api

    w = _persisted(tmp_path)
    w.publish(DECISION)

    def broken(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("malformed manifest (exit 4)")

    monkeypatch.setattr(api, "info", broken)
    report = w.import_pages()

    assert report.import_error is not None and "manifest" in report.import_error
    assert report.imported == [] and w.wiki_memories() == []
    assert not (tmp_path / "state" / "wiki-sync").exists()


def test_a_manifest_without_a_wiki_id_uses_the_path_hash_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    from wiki_studio import api

    from memkernel.wiki.ledger import wiki_key

    w = _persisted(tmp_path)
    w.publish(DECISION)
    monkeypatch.setattr(api, "info", lambda *a, **k: SimpleNamespace(manifest=SimpleNamespace(wiki_id=None)))
    w.import_pages()

    expected = wiki_key(None, w.wiki, w.root)
    assert (tmp_path / "state" / "wiki-sync" / w.svc.project_id / f"{expected}.json").is_file()


def test_an_already_withdrawn_deprecated_page_is_not_listed_as_skipped(tmp_path: Path) -> None:
    """FR-006: after the withdrawal, later imports neither withdraw it again nor list it in skipped."""
    w = Wiki(tmp_path)
    rel, _ = w.publish(DECISION)
    w.import_pages()
    w.update(rel, lambda t: t.replace("status: stable", "status: deprecated", 1))
    w.approve(rel)
    assert [x["path"] for x in w.import_pages().withdrawn] == [rel]

    again = w.import_pages()

    assert again.withdrawn == [] and rel not in again.skipped

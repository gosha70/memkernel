# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""Governed mode, curation debt, export batches and source revisions against the real wiki-studio
(memkernel-0-7-governed SC-1 to SC-5)."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import time
import uuid
from typing import TYPE_CHECKING, Any

import chromadb
import pytest

from memkernel.config import MemKernelSettings
from memkernel.core.models import MemoryTier, MemoryType
from memkernel.factory import build_service
from memkernel.lifecycle import CONTEXT_BUDGET, TOTAL_BUDGET, MemoryLifecycle
from memkernel.wiki import curation, studio, sync
from memkernel.wiki.curation import CURATION_HINT, HEADING_CURATION_DEBT, UNAVAILABLE_PREFIX
from memkernel.wiki.ledger import (
    ACTION_IMPORT,
    LEDGER_DIR,
    STATE_FAILED,
    LedgerEntry,
    SyncLedger,
    wiki_key,
)
from memkernel.wiki.pages import parse_page
from memkernel.wiki.studio import GateUncertainError
from memkernel.wiki.sync import UNGATED_LINT_HINT, WikiExporter, WikiImporter
from tests.conftest import MockEmbedding
from tests.integration.curation_hooks import MARKER_ENV
from tests.integration.test_wiki_import_governed import DECISION, OTHER, Wiki
from tests.unit.test_wiki import NO_EXTRA_ENV, _service

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.integration

try:  # fails, never skips, without wiki-studio, unless MK_TEST_NO_EXTRA=1 marks a deliberate no-extra run
    import wiki_studio.api as api
except ImportError:
    if os.environ.get(NO_EXTRA_ENV) == "1":
        pytest.skip("deliberate no-extra run", allow_module_level=True)
    raise

BOUND = 2.5  # G2: deadline 2.0 + terminate grace 0.3 + kill grace 0.2
SLACK = 0.3  # the test's own process overhead around the bound
HOOKS = "tests.integration.curation_hooks"


def _governed(w: Wiki) -> Wiki:
    """Turn the managed wiki ``api.init`` made into a governed one (approval_required)."""
    manifest = w.wiki / studio.MANIFEST_FILE
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["policy"]["approval_required"] = True
    manifest.write_text(json.dumps(data), encoding="utf-8")
    return w


def _wiki(tmp_path: Path, mode: str = "governed", governed: bool = True, **settings: Any) -> Wiki:
    w = Wiki(tmp_path, _service(wiki_mode=mode, **settings))
    return _governed(w) if governed else w


def _tree(w: Wiki) -> dict[str, bytes]:
    return {
        p.relative_to(w.root).as_posix(): p.read_bytes()
        for p in sorted(w.root.rglob("*"))
        if p.is_file() and ".audit" not in p.parts and "wiki-proposals" not in p.parts
    }


def _no_studio(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every way into wiki-studio raises: ungated must never take one."""

    def boom(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("wiki-studio was touched")

    for module in (studio, sync, curation):
        for name in ("load_studio", "gate_available", "lint_wiki", "review_pages", "curation_findings"):
            if hasattr(module, name):
                monkeypatch.setattr(module, name, boom)


# ── SC-1: governed refuses, writing nothing ──────────────────────────────────


def _refusals() -> list[tuple[str, Any]]:
    def absent(w: Wiki, mp: pytest.MonkeyPatch) -> None:
        mp.setattr(studio, "load_studio", lambda **_: None)

    def old(w: Wiki, mp: pytest.MonkeyPatch) -> None:
        mp.setattr(studio.metadata, "version", lambda name: "0.6.0")

    def no_page_id(w: Wiki, mp: pytest.MonkeyPatch) -> None:
        real = api.info
        mp.setattr(
            api,
            "info",
            lambda paths: dataclasses.replace(
                real(paths), capabilities=tuple(c for c in real(paths).capabilities if c != "page-id")
            ),
        )

    def managed(w: Wiki, mp: pytest.MonkeyPatch) -> None:
        data = json.loads((w.wiki / studio.MANIFEST_FILE).read_text(encoding="utf-8"))
        data["policy"]["approval_required"] = False
        (w.wiki / studio.MANIFEST_FILE).write_text(json.dumps(data), encoding="utf-8")

    def legacy(w: Wiki, mp: pytest.MonkeyPatch) -> None:
        (w.wiki / studio.MANIFEST_FILE).unlink()

    def drift(w: Wiki, mp: pytest.MonkeyPatch) -> None:
        real = api.info
        mp.setattr(api, "info", lambda paths: dataclasses.replace(real(paths), warnings=("schema drift: x",)))

    return [
        ("not installed", absent),
        ("needs wiki-studio >= 0.7.0", old),
        ("lacks the capabilities page-id", no_page_id),
        ("is managed, not governed", managed),
        ("is legacy, not governed", legacy),
        ("schema has drifted", drift),
    ]


@pytest.mark.parametrize(("expected", "breaks"), _refusals(), ids=[r[0] for r in _refusals()])
def test_governed_export_and_import_refuse_and_write_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, expected: str, breaks: Any
) -> None:
    w = _wiki(tmp_path)
    w.svc.retain(DECISION, MemoryType.DECISION)
    breaks(w, monkeypatch)
    before = _tree(w)

    def unread(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("the export looked at the wiki before the preflight passed")

    monkeypatch.setattr(WikiExporter, "_page_for", unread)

    export = WikiExporter(w.svc, w.wiki, project_root=w.root, proposals_dir=w.proposals).export()
    imported = w.import_pages()

    assert export.written == [] and expected in (export.gate_error or ""), export.gate_error
    assert (export.mode, export.configured_mode, export.remaining) == ("gated", "governed", None)
    assert export.lint is None and export.lint_error is None and export.skipped == 0  # nothing read, nothing linted
    assert imported.imported == [] and expected in (imported.import_error or ""), imported.import_error
    assert (imported.mode, imported.configured_mode) == ("gated", "governed")
    assert _tree(w) == before and w.wiki_memories() == []
    assert not (tmp_path / "state").exists() and not (w.root / ".memkernel" / "state").exists()


def test_governed_runs_through_the_gate_and_refuses_update_index_false(tmp_path: Path) -> None:
    w = _wiki(tmp_path)
    rel, _ = w.publish(DECISION)

    imported = w.import_pages()
    w.svc.retain(OTHER, MemoryType.DECISION)
    unindexed = WikiExporter(w.svc, w.wiki, project_root=w.root, proposals_dir=w.proposals).export(update_index=False)

    assert imported.governed is True and imported.imported == [rel] and imported.mode == "gated"
    assert unindexed.written == [] and "update_index=False is refused" in (unindexed.gate_error or "")


def test_a_gate_rejection_after_init_keeps_only_the_scaffold(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    w = _wiki(tmp_path)
    (w.wiki / "index.md").unlink()
    (w.wiki / "log.md").unlink()
    w.svc.retain(DECISION, MemoryType.DECISION)

    def rejected(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("rejected by a reviewer")

    monkeypatch.setattr(api, "propose", rejected)
    report = WikiExporter(w.svc, w.wiki, project_root=w.root, proposals_dir=w.proposals).export()

    assert report.written == [] and "gate rejected the export" in (report.gate_error or "")
    assert (w.wiki / "index.md").is_file() and (w.wiki / "log.md").is_file()  # api.init's scaffold stays
    assert not (w.wiki / "decisions").exists() and report.remaining == 1


def test_ungated_never_touches_wiki_studio(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    w = _wiki(tmp_path, mode="ungated")
    w.svc.retain(DECISION, MemoryType.DECISION)
    _no_studio(monkeypatch)

    export = WikiExporter(w.svc, w.wiki, project_root=w.root).export()
    page = w.wiki / export.written[0]
    page.write_text(page.read_text(encoding="utf-8").replace("status: draft", "status: stable"), encoding="utf-8")
    imported = w.import_pages()
    block = MemoryLifecycle(w.svc, w.svc.settings.model_copy(update={"wiki_dir": str(w.wiki)})).on_session_start()

    assert export.gated is False and export.lint is None and export.written
    assert (export.mode, export.configured_mode) == ("ungated", "ungated")
    assert imported.governed is False and imported.imported == export.written
    assert (imported.mode, imported.configured_mode) == ("ungated", "ungated")
    assert HEADING_CURATION_DEBT not in block


def test_auto_with_wiki_studio_is_gated_and_reads_a_managed_wiki(tmp_path: Path) -> None:
    w = _wiki(tmp_path, mode="auto", governed=False)
    rel, _ = w.publish(DECISION)
    imported = w.import_pages()
    w.svc.retain(OTHER, MemoryType.DECISION)  # stays a draft: unapproved, so curation debt
    export = WikiExporter(w.svc, w.wiki, project_root=w.root, proposals_dir=w.proposals).export()
    settings = w.svc.settings.model_copy(update={"wiki_dir": str(w.wiki), "project_root": str(w.root)})

    block = MemoryLifecycle(w.svc, settings).on_session_start()

    assert (export.mode, export.configured_mode) == ("gated", "auto") and export.gated and export.written
    assert (imported.mode, imported.configured_mode) == ("gated", "auto") and imported.imported == [rel]
    assert f"{HEADING_CURATION_DEBT}\nunapproved 1" in block


def test_auto_without_wiki_studio_is_ungated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    svc = _service()
    svc.retain(DECISION, MemoryType.DECISION)
    monkeypatch.setattr(sync, "gate_available", lambda: None)
    monkeypatch.setattr(sync, "studio_installed", lambda: False)
    monkeypatch.setattr(sync, "lint_wiki", lambda *a, **k: None)

    export = WikiExporter(svc, tmp_path / "wiki", project_root=tmp_path).export()
    imported = WikiImporter(svc, tmp_path / "wiki", project_root=tmp_path).import_pages()

    assert (export.mode, export.configured_mode) == ("ungated", "auto") and export.written
    assert (imported.mode, imported.configured_mode) == ("ungated", "auto")


@pytest.mark.e2e
async def test_the_tools_report_the_mode(tmp_path: Path) -> None:
    from mcp.shared.memory import create_connected_server_and_client_session

    from memkernel.mcp.server import create_server

    settings = MemKernelSettings(
        project_id=f"mode-{uuid.uuid4().hex[:8]}",
        chroma_persist_path="",
        wiki_dir=str(tmp_path / "wiki"),
        project_root=str(tmp_path),
        wiki_mode="ungated",
    )
    server = create_server(settings=settings, embedding=MockEmbedding(dimension=384))
    async with create_connected_server_and_client_session(server) as client:
        await client.call_tool("retain", arguments={"content": DECISION, "type": "decision"})
        export = json.loads((await client.call_tool("wiki_export", arguments={})).content[0].text)  # type: ignore[union-attr]
        imported = json.loads((await client.call_tool("wiki_import", arguments={})).content[0].text)  # type: ignore[union-attr]

    assert (export["mode"], export["configured_mode"], export["remaining"]) == ("ungated", "ungated", 0)
    assert export["lint"] is None and export["lint_hint"] == UNGATED_LINT_HINT
    assert (imported["mode"], imported["configured_mode"]) == ("ungated", "ungated")


# ── SC-3: export batches ──────────────────────────────────────────────────────


def _twelve(svc: Any) -> list[str]:
    """12 exportable memories: importance 0.9 for the last four retained, 0.5 for the rest (oldest first)."""
    return [
        svc.retain(f"Decision number {i:02d}\n\nBecause {i}.", MemoryType.DECISION, importance=0.9 if i >= 8 else 0.5)
        for i in range(12)
    ]


def test_an_export_writes_one_batch_in_order_and_reports_what_remains(tmp_path: Path) -> None:
    svc = _service(wiki_mode="ungated")
    refs = _twelve(svc)
    exporter = WikiExporter(svc, tmp_path / "wiki", project_root=tmp_path)

    first, second = exporter.export(), exporter.export()

    order = refs[8:] + refs[:8]  # the most important first, ties by age
    assert [_ref(tmp_path / "wiki" / rel) for rel in first.written] == order[:10] and first.remaining == 2
    assert [_ref(tmp_path / "wiki" / rel) for rel in second.written] == order[10:] and second.remaining == 0


def test_batch_zero_writes_everything(tmp_path: Path) -> None:
    svc = _service(wiki_mode="ungated", wiki_export_batch=0)
    _twelve(svc)
    report = WikiExporter(svc, tmp_path / "wiki", project_root=tmp_path).export()
    assert len(report.written) == 12 and report.remaining == 0


def test_a_rejected_batch_leaves_all_remaining_and_an_uncertain_one_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    w = _wiki(tmp_path)
    _twelve(w.svc)

    def rejected(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("rejected")

    with monkeypatch.context() as patch:
        patch.setattr(api, "promote", rejected)
        report = WikiExporter(w.svc, w.wiki, project_root=w.root, proposals_dir=w.proposals).export()
    assert report.written == [] and report.gate_error and report.remaining == 12

    def uncertain(*args: Any, **kwargs: Any) -> Any:
        raise GateUncertainError("failed", proposal="p", uncertain_outcome="pages may be on disk", receipt_error=None)

    monkeypatch.setattr(sync, "propose_and_promote", uncertain)
    report = WikiExporter(w.svc, w.wiki, project_root=w.root, proposals_dir=w.proposals).export()
    assert report.uncertain_outcome and report.remaining is None


def _ref(page_path: Path) -> str:
    page = parse_page(page_path.read_text(encoding="utf-8"))
    assert page is not None
    return page.extra["memkernel_ref"]


# ── SC-4: source revision and content hash ────────────────────────────────────


def _git(root: Path, *args: str) -> str:
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t"}
    env["GIT_COMMITTER_EMAIL"] = "t@t"
    return subprocess.run(  # noqa: S603
        ["git", "-C", str(root), *args],  # noqa: S607
        check=True,
        capture_output=True,
        text=True,
        env=env,
    ).stdout.strip()


def _sources(page_path: Path) -> list[dict[str, str]]:
    page = parse_page(page_path.read_text(encoding="utf-8"))
    assert page is not None
    return page.sources


def test_a_clean_tracked_source_gets_its_commit_and_every_page_its_hash(tmp_path: Path) -> None:
    w = Wiki(tmp_path, _service())  # auto, managed: the pages pass the real gate
    _git(tmp_path, "init", "-q")
    for name in ("clean.py", "modified.py", "staged.py"):
        (tmp_path / name).write_text("x = 1\n")
    _git(tmp_path, "add", "clean.py", "modified.py", "staged.py")
    _git(tmp_path, "commit", "-q", "-m", "sources")
    (tmp_path / "modified.py").write_text("x = 2\n")
    (tmp_path / "staged.py").write_text("x = 3\n")
    _git(tmp_path, "add", "staged.py")
    (tmp_path / "untracked.py").write_text("x = 4\n")
    sources = ["clean.py", "modified.py", "staged.py", "untracked.py"]
    refs = {
        w.svc.retain(f"Decision about {name}\n\nIt matters.", MemoryType.DECISION, source=name): name
        for name in sources
    }

    report = WikiExporter(w.svc, w.wiki, project_root=w.root, proposals_dir=w.proposals).export()

    assert report.gated and len(report.written) == 4, report.gate_error
    commit = _git(tmp_path, "log", "-1", "--format=%h", "--", "clean.py")
    for rel in report.written:
        page = parse_page((w.wiki / rel).read_text(encoding="utf-8"))
        assert page is not None
        memory = w.svc.get(page.extra["memkernel_ref"], touch=False)
        assert memory is not None and page.extra["memkernel_sha256"] == memory.content_hash
        (path_source,) = [s for s in page.sources if "path" in s]
        expected = {"path": refs[memory.ref_id], **({"sha": commit} if refs[memory.ref_id] == "clean.py" else {})}
        assert path_source == expected


def test_no_git_gives_no_commit(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("x = 1\n")
    svc = _service(wiki_mode="ungated")
    svc.retain("Decision about a\n\nIt matters.", MemoryType.DECISION, source="a.py")
    report = WikiExporter(svc, tmp_path / "wiki", project_root=tmp_path).export()
    assert _sources(tmp_path / "wiki" / report.written[0])[1] == {"path": "a.py"}


def test_a_submodule_file_never_takes_the_submodules_commit(tmp_path: Path) -> None:
    sub = tmp_path / "sub-origin"
    sub.mkdir()
    _git(sub, "init", "-q")
    (sub / "inner.py").write_text("x = 1\n")
    _git(sub, "add", "inner.py")
    _git(sub, "commit", "-q", "-m", "inner")
    project = tmp_path / "project"
    project.mkdir()
    _git(project, "init", "-q")
    _git(project, "-c", "protocol.file.allow=always", "submodule", "add", "-q", str(sub), "vendor")
    _git(project, "commit", "-q", "-m", "submodule")
    svc = _service(wiki_mode="ungated")
    svc.retain("Decision about inner\n\nIt matters.", MemoryType.DECISION, source="vendor/inner.py")

    report = WikiExporter(svc, project / "wiki", project_root=project).export()

    assert _sources(project / "wiki" / report.written[0])[1] == {"path": "vendor/inner.py"}


# ── SC-5: page_id ─────────────────────────────────────────────────────────────


def test_a_renamed_page_keeps_its_memory(tmp_path: Path) -> None:
    w = _wiki(tmp_path)
    rel, _ = w.publish(DECISION)
    w.import_pages()
    (before,) = w.wiki_memories()
    text = (w.wiki / rel).read_text(encoding="utf-8")
    page = parse_page(text)
    assert page is not None and page.extra.get("page_id", "").startswith("pg-")  # G5

    old_slug = rel.rsplit("/", 1)[1].removesuffix(".md")
    renamed = f"decisions/{old_slug}-renamed.md"
    (w.wiki / renamed).write_text(text.replace(f"slug: {old_slug}", f"slug: {old_slug}-renamed", 1))
    (w.wiki / rel).unlink()
    index = w.wiki / "index.md"
    index.write_text(index.read_text(encoding="utf-8").replace(f"]({rel})", f"]({renamed})"), encoding="utf-8")
    w.approve(renamed)
    report = w.import_pages()

    (after,) = w.wiki_memories()
    assert report.import_error is None and report.withdrawn == []
    assert after.supersedes == before.ref_id and after.source == renamed  # one live memory, its history kept


def _move_unchanged(w: Wiki) -> tuple[str, str, Any, bytes]:
    """Publish and import a page, then move it to another directory with identical bytes; return (old path, new
    path, the memory before the move, the bytes)."""
    rel, _ = w.publish(DECISION)
    w.import_pages()
    (before,) = w.wiki_memories()
    moved = f"decisions/archive/{rel.rsplit('/', 1)[1]}"
    data = (w.wiki / rel).read_bytes()
    (w.wiki / moved).parent.mkdir(parents=True)
    (w.wiki / moved).write_bytes(data)
    (w.wiki / rel).unlink()
    index = w.wiki / "index.md"
    index.write_text(index.read_text(encoding="utf-8").replace(f"]({rel})", f"]({moved})"), encoding="utf-8")
    return rel, moved, before, data


def _new_page_at(w: Wiki, rel: str, data: bytes) -> None:
    """A new page (no page_id, other content) at ``rel``, linked from the index."""
    text = data.decode("utf-8").replace("Because of concurrent writes.", "Because of a new requirement.", 1)
    (w.wiki / rel).write_text(re.sub(r"^page_id: .*\n", "", text, count=1, flags=re.M), encoding="utf-8")
    index = w.wiki / "index.md"
    index.write_text(index.read_text(encoding="utf-8") + f"- [New]({rel}) — a new page at the old path.\n")


def test_a_page_moved_with_identical_bytes_keeps_its_memory(tmp_path: Path) -> None:
    """G5: wiki-studio's approval follows the page_id and the bytes, so a page moved to another directory unchanged
    is approved there without a new approval (approve itself would refuse the move: a decision belongs under
    decisions/). Its memory moves with it. A new page at the old path shares the moved page's slug, which
    wiki-studio refuses to approve, so it is not imported."""
    w = _wiki(tmp_path)
    rel, moved, before, data = _move_unchanged(w)
    assert {s.path: (s.state, s.reason) for s in api.review_state(w.paths)}[moved] == (
        "approved",
        "record_matches_live",
    )

    after_move = w.import_pages()
    (kept,) = w.wiki_memories()
    assert after_move.imported == [moved] and after_move.unchanged == []
    assert kept.source == moved and kept.supersedes == before.ref_id

    _new_page_at(w, rel, data)
    with pytest.raises(Exception, match="duplicate slug"):
        w.approve(rel)
    after_new = w.import_pages()
    assert [entry["path"] for entry in after_new.not_approved] == [rel]
    assert [m.ref_id for m in w.wiki_memories()] == [kept.ref_id]  # the moved page keeps its memory


def test_a_new_page_at_a_moved_pages_old_path_never_takes_its_memory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The same move, with the new page at the old path reported approved (wiki-studio refuses that approval while
    the slugs collide, so its review is added here): it gets a memory of its own; the moved page keeps its own."""
    w = _wiki(tmp_path)
    rel, moved, before, data = _move_unchanged(w)
    w.import_pages()
    (kept,) = w.wiki_memories()
    _new_page_at(w, rel, data)
    real = sync.review_pages

    def with_new_page_approved(*args: Any) -> list[Any]:
        text = (w.wiki / rel).read_text(encoding="utf-8")
        sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
        reviews = [r for r in real(*args) if r.path != rel]
        return [*reviews, studio.PageReview(rel, rel, "approved", "record_matches_live", text, sha)]

    monkeypatch.setattr(sync, "review_pages", with_new_page_approved)
    report = w.import_pages()

    live = {m.source: m for m in w.wiki_memories()}
    assert report.imported == [rel] and report.import_error is None
    assert live[moved].ref_id == kept.ref_id and kept.supersedes == before.ref_id
    assert live[rel].ref_id not in (kept.ref_id, before.ref_id) and live[rel].supersedes is None


# ── SC-2: curation debt ───────────────────────────────────────────────────────


def _debt(w: Wiki, hook: str | None = None, monkeypatch: pytest.MonkeyPatch | None = None, **over: Any) -> list[str]:
    if hook is not None and monkeypatch is not None:
        monkeypatch.setattr(curation, "TEST_HOOK", f"{HOOKS}:{hook}")
    settings = w.svc.settings.model_copy(update={"wiki_dir": str(w.wiki), "project_root": str(w.root), **over})
    return list(curation.curation_debt_lines(settings, settings, w.svc.project_id))


def _stale_and_unapproved(w: Wiki) -> tuple[str, str]:
    stale, _ = w.publish(DECISION)
    w.update(stale, lambda text: text.replace("Because of concurrent writes.", "Because of many writes.", 1))
    w.svc.retain(OTHER, MemoryType.DECISION)
    (unapproved,) = w.export()
    return stale, unapproved


def _failed_entry(w: Wiki) -> None:
    ident = studio.read_wiki_id(w.wiki)
    ledger = SyncLedger.for_wiki(w.svc.settings.state_dir, False, w.svc.project_id, ident, w.wiki, w.root)
    with ledger.run():
        ledger.mark(LedgerEntry("k", "decisions/gone.md", STATE_FAILED, ACTION_IMPORT), STATE_FAILED, "boom")


def _record_budgets(module: Any, monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Every budget ``lifecycle._fit`` is called with, in order; the first is the context share's."""
    budgets: list[int] = []
    real_fit = module._fit

    def fit(lines: list[str], budget: int) -> list[str]:
        budgets.append(budget)
        return list(real_fit(lines, budget))

    monkeypatch.setattr(module, "_fit", fit)
    return budgets


def test_the_startup_block_shows_the_debt_within_budget(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from memkernel import lifecycle as module

    w = _wiki(tmp_path)
    stale, unapproved = _stale_and_unapproved(w)
    _failed_entry(w)
    for i in range(30):
        w.svc.retain(f"Decision {i}: " + "y" * 300, MemoryType.DECISION)
    w.svc.retain("SESSION CHECKPOINT\n\n" + "x" * 9000, MemoryType.EPISODE, checkpoint=True)
    budgets = _record_budgets(module, monkeypatch)
    settings = w.svc.settings.model_copy(update={"wiki_dir": str(w.wiki), "project_root": str(w.root)})

    block = MemoryLifecycle(w.svc, settings).on_session_start("startup")

    section = block[block.index(HEADING_CURATION_DEBT) - 1 :].split("\n---\n")[0].rstrip("\n")
    lines = section.split("\n")
    assert lines[2].startswith("unapproved 1, approval-stale 1") and lines[2].endswith("sync failed 1"), lines
    debt = '<stored-memory kind="debt">{}</stored-memory>'  # the page paths come from the wiki: quoted as data (#85)
    assert lines[3:5] == [f"- unapproved: {debt.format(unapproved)}", f"- approval-stale: {debt.format(stale)}"]
    assert lines[-1] == CURATION_HINT
    assert len(section) <= curation.CURATION_DEBT_BUDGET and len(block) <= TOTAL_BUDGET
    assert budgets[0] == CONTEXT_BUDGET - len(section)  # the context share gives up exactly the section


def test_no_debt_no_section_and_the_full_context_share(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from memkernel import lifecycle as module

    w = _wiki(tmp_path)
    budgets = _record_budgets(module, monkeypatch)
    settings = w.svc.settings.model_copy(update={"wiki_dir": str(w.wiki), "project_root": str(w.root)})
    w.svc.retain(DECISION, MemoryType.DECISION)

    block = MemoryLifecycle(w.svc, settings).on_session_start("startup")

    assert HEADING_CURATION_DEBT not in block and budgets[0] == CONTEXT_BUDGET


@pytest.mark.parametrize("source", ["compact", "resume", "fork"])
def test_only_the_full_block_has_the_debt(tmp_path: Path, source: str) -> None:
    w = _wiki(tmp_path)
    _stale_and_unapproved(w)
    settings = w.svc.settings.model_copy(update={"wiki_dir": str(w.wiki), "project_root": str(w.root)})
    assert HEADING_CURATION_DEBT not in MemoryLifecycle(w.svc, settings).on_session_start(source)


def test_governed_with_a_managed_wiki_never_calls_findings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    w = _wiki(tmp_path, governed=False)
    marker = tmp_path / "reached"
    monkeypatch.setenv(MARKER_ENV, str(marker))
    lines = _debt(w, "mark_findings", monkeypatch)
    assert lines[2].startswith(UNAVAILABLE_PREFIX) and "is managed, not governed" in lines[2]
    assert not marker.exists()


def _unavailable(lines: list[str], reason: str) -> None:
    assert lines[:2] == ["", HEADING_CURATION_DEBT] and len(lines) == 3, lines
    assert lines[2].startswith(UNAVAILABLE_PREFIX) and reason in lines[2], lines


@pytest.mark.parametrize(
    ("hook", "reason"),
    [
        ("findings_raise", "findings broke"),
        ("raise_at_start", curation.NO_RESULT),
        ("exit_at_start", curation.NO_RESULT),
        ("slow_findings", curation.TIMED_OUT),
        ("slow_send", curation.TIMED_OUT),
        ("ignore_term", curation.TIMED_OUT),
    ],
)
def test_each_child_failure_is_one_line_within_the_bound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, hook: str, reason: str
) -> None:
    w = _wiki(tmp_path)
    _stale_and_unapproved(w)
    start = time.monotonic()
    lines = _debt(w, hook, monkeypatch)
    assert time.monotonic() - start < BOUND + SLACK
    _unavailable(lines, reason)
    assert curation.multiprocessing.active_children() == []


def test_the_child_succeeds_within_the_bound(tmp_path: Path) -> None:
    w = _wiki(tmp_path)
    _stale_and_unapproved(w)
    start = time.monotonic()
    lines = _debt(w)
    assert time.monotonic() - start < BOUND
    assert lines[2].startswith("unapproved 1, approval-stale 1")


def test_a_start_that_raises_is_one_line(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    w = _wiki(tmp_path)

    def broken(self: Any) -> None:
        raise OSError("no more processes")

    monkeypatch.setattr(curation._CONTEXT.Process, "start", broken)
    _unavailable(_debt(w), "no more processes")


def test_an_in_memory_ledger_an_import_holds_is_one_line(tmp_path: Path) -> None:
    w = _wiki(tmp_path)
    _stale_and_unapproved(w)
    held, release = threading.Event(), threading.Event()
    ledger = SyncLedger.for_wiki("", False, w.svc.project_id, studio.read_wiki_id(w.wiki), w.wiki, w.root)

    def importing() -> None:
        with ledger.run():
            held.set()
            release.wait(10)

    thread = threading.Thread(target=importing)
    thread.start()
    try:
        assert held.wait(10)
        _unavailable(_debt(w), "an import holds the sync ledger")
    finally:
        release.set()
        thread.join(10)


# ── SC-2: the on-disk ledger snapshot ─────────────────────────────────────────


def _persisted(tmp_path: Path) -> Wiki:
    settings = {"chroma_persist_path": str(tmp_path / "chroma"), "state_dir": str(tmp_path / "state")}
    w = Wiki(tmp_path, _persisted_service(**settings))
    return _governed(w)


def _persisted_service(**overrides: Any) -> Any:
    settings = MemKernelSettings(project_id=f"gov-{uuid.uuid4().hex[:8]}", wiki_mode="governed", **overrides)
    return build_service(settings, embedding=MockEmbedding(), chroma_client=chromadb.EphemeralClient())


def _ledger_dir(w: Wiki) -> Path:
    from pathlib import Path

    return Path(w.svc.settings.state_dir) / LEDGER_DIR / w.svc.project_id


def _key(w: Wiki) -> str:
    return wiki_key(studio.read_wiki_id(w.wiki), w.wiki, w.root)


def _listing(directory: Path) -> dict[str, bytes]:
    return {p.name: p.read_bytes() for p in sorted(directory.iterdir())} if directory.exists() else {}


_HOLDER = r"""
import fcntl, sys, time
from pathlib import Path
lock = Path(sys.argv[1])
lock.parent.mkdir(parents=True, exist_ok=True)
with lock.open("a") as handle:
    fcntl.flock(handle, fcntl.LOCK_EX)
    Path(sys.argv[2]).write_text("held")
    time.sleep(30)
"""


@pytest.mark.parametrize("first_import", [False, True])
def test_an_on_disk_ledger_another_process_holds_is_one_line(tmp_path: Path, first_import: bool) -> None:
    w = _persisted(tmp_path)
    _stale_and_unapproved(w)
    ledger = _ledger_dir(w) / f"{_key(w)}.json"
    if not first_import:  # an earlier import's ledger; otherwise the holder creates the directory and lock itself
        ledger.parent.mkdir(parents=True)
        ledger.write_text(json.dumps({"version": 1, "entries": {}}))
    before = _listing(ledger.parent)
    held = tmp_path / "held"
    holder = subprocess.Popen([sys.executable, "-c", _HOLDER, f"{ledger}.lock", str(held)])  # noqa: S603
    try:
        deadline = time.monotonic() + 30
        while not held.exists():
            assert time.monotonic() < deadline and holder.poll() is None
            time.sleep(0.02)
        _unavailable(_debt(w), "an import holds the sync ledger")
        after = _listing(ledger.parent)
        assert {k: v for k, v in after.items() if not k.endswith(".lock")} == {
            k: v for k, v in before.items() if not k.endswith(".lock")
        }
    finally:
        holder.kill()
        holder.wait(10)


def test_no_ledger_directory_counts_zero_and_creates_nothing(tmp_path: Path) -> None:
    w = _persisted(tmp_path)
    _stale_and_unapproved(w)
    lines = _debt(w)
    assert "sync" not in lines[2] and not _ledger_dir(w).exists()


def test_a_ledger_directory_without_this_wikis_lock_file(tmp_path: Path) -> None:
    w = _persisted(tmp_path)
    _stale_and_unapproved(w)
    ledger = _ledger_dir(w) / f"{_key(w)}.json"
    ledger.parent.mkdir(parents=True)
    entry = {"page_key": "k", "path": "decisions/x.md", "state": "failed", "action": "import"}
    ledger.write_text(json.dumps({"version": 1, "entries": {"k": entry}}))
    data = ledger.read_bytes()

    lines = _debt(w)

    assert lines[2].endswith("sync failed 1")
    assert ledger.read_bytes() == data and (ledger.parent / f"{ledger.name}.lock").read_bytes() == b""
    assert sorted(p.name for p in ledger.parent.iterdir()) == sorted([ledger.name, f"{ledger.name}.lock"])


def test_a_corrupt_ledger_is_one_line_and_left_as_it_is(tmp_path: Path) -> None:
    w = _persisted(tmp_path)
    _stale_and_unapproved(w)
    ledger = _ledger_dir(w) / f"{_key(w)}.json"
    ledger.parent.mkdir(parents=True)
    ledger.write_text("{not json")

    _unavailable(_debt(w), "could not be read")

    assert ledger.read_text() == "{not json"
    assert sorted(p.name for p in ledger.parent.iterdir()) == sorted([ledger.name, f"{ledger.name}.lock"])


# ── SC-2: twenty session starts in one process ────────────────────────────────


def test_repeated_starts_leave_no_child_and_no_descriptor(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    w = _persisted(tmp_path)
    _stale_and_unapproved(w)
    fds = len(os.listdir("/dev/fd"))
    for i in range(20):
        monkeypatch.setattr(curation, "TEST_HOOK", f"{HOOKS}:slow_findings" if i % 2 else None)
        lines = _debt(w)
        assert (UNAVAILABLE_PREFIX in lines[2]) == bool(i % 2), (i, lines)
    assert curation.multiprocessing.active_children() == []
    assert len(os.listdir("/dev/fd")) == fds
    ledger = SyncLedger.for_wiki(w.svc.settings.state_dir, True, w.svc.project_id, None, w.wiki, w.root)
    started = time.monotonic()
    with ledger.run():
        assert time.monotonic() - started < 1.0  # an import takes the ledger at once
    assert MemoryTier.LONG_TERM  # the store itself is untouched by the debt


def test_a_git_that_times_out_is_asked_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def hung(argv: list[str], **kwargs: Any) -> Any:
        calls.append(argv)
        raise subprocess.TimeoutExpired(argv, sync.GIT_TIMEOUT_SECONDS)

    monkeypatch.setattr(sync.subprocess, "run", hung)
    (tmp_path / "a.py").write_text("x = 1\n")
    (tmp_path / "b.py").write_text("x = 2\n")
    svc = _service(wiki_mode="ungated")
    for name in ("a.py", "b.py"):
        svc.retain(f"Decision about {name}\n\nIt matters.", MemoryType.DECISION, source=name)

    report = WikiExporter(svc, tmp_path / "wiki", project_root=tmp_path).export()

    assert len(report.written) == 2 and len(calls) == 1


def test_a_result_that_cannot_be_received_is_one_line(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from multiprocessing.connection import Connection

    w = _wiki(tmp_path)
    _stale_and_unapproved(w)

    def unreadable(self: Any) -> Any:
        raise ValueError("unpicklable")

    monkeypatch.setattr(Connection, "recv", unreadable)
    _unavailable(_debt(w), curation.NO_RESULT)
    assert curation.multiprocessing.active_children() == []


def test_the_bound_starts_once_the_child_has_started(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """G2 as the owner decided on 2026-11-04: a slow Process.start() does not eat into the check's 2.0 seconds."""
    w = _wiki(tmp_path)
    _stale_and_unapproved(w)
    real = curation._CONTEXT.Process.start

    def slow(self: Any) -> None:
        time.sleep(curation.CURATION_DEBT_TIMEOUT_SECONDS + 0.5)  # a deadline taken before it would have passed
        real(self)

    monkeypatch.setattr(curation._CONTEXT.Process, "start", slow)
    lines = _debt(w)
    assert lines[2].startswith("unapproved 1"), lines
    assert curation.multiprocessing.active_children() == []


def test_a_pipe_that_cannot_be_allocated_is_one_line(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    w = _wiki(tmp_path)

    def exhausted(*args: Any, **kwargs: Any) -> Any:
        raise OSError(24, "Too many open files")

    monkeypatch.setattr(curation._CONTEXT, "Pipe", exhausted)
    _unavailable(_debt(w), "Too many open files")


def test_a_symlinked_source_cites_its_own_commit(tmp_path: Path) -> None:
    _git(tmp_path, "init", "-q")
    (tmp_path / "target.py").write_text("x = 1\n")
    (tmp_path / "alias.py").symlink_to("target.py")
    _git(tmp_path, "add", "target.py", "alias.py")
    _git(tmp_path, "commit", "-q", "-m", "both")
    (tmp_path / "target.py").write_text("x = 2\n")
    _git(tmp_path, "commit", "-q", "-am", "target only")
    svc = _service(wiki_mode="ungated")
    svc.retain("Decision about alias\n\nIt matters.", MemoryType.DECISION, source="alias.py")

    report = WikiExporter(svc, tmp_path / "wiki", project_root=tmp_path).export()

    alias_commit = _git(tmp_path, "log", "-1", "--format=%h", "--", "alias.py")
    assert alias_commit != _git(tmp_path, "log", "-1", "--format=%h", "--", "target.py")
    assert _sources(tmp_path / "wiki" / report.written[0])[1] == {"path": "alias.py", "sha": alias_commit}


def test_a_negative_batch_is_refused() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        MemKernelSettings(wiki_export_batch=-1)


def test_a_close_that_fails_still_reaps_the_child(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from multiprocessing.connection import Connection

    w = _wiki(tmp_path)
    _stale_and_unapproved(w)
    real_close = Connection.close

    def failing(self: Any) -> None:
        real_close(self)
        raise OSError("close failed")

    monkeypatch.setattr(Connection, "close", failing)
    lines = _debt(w)
    assert lines[2].startswith("unapproved 1"), lines
    assert curation.multiprocessing.active_children() == []

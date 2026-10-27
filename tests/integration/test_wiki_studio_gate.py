# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""The combined gate against the real wiki-studio (memkernel-0-6 SC-1 to SC-4, SC-6).

"Another writer" is wiki-studio's own API (``init`` / ``propose`` / ``promote``)
used directly, as a curator or a second agent would, interleaved with a
memkernel export between its propose and its promote.
"""

from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from memkernel.core.models import MemoryType
from memkernel.wiki.pages import render_page
from memkernel.wiki.sync import DEFAULT_PROPOSALS_SUBDIR, WikiExporter
from tests.unit.test_wiki import NO_EXTRA_ENV, _service

if TYPE_CHECKING:
    from collections.abc import Callable

    from memkernel.core.services import MemoryService

pytestmark = pytest.mark.integration

try:  # fails, never skips, without wiki-studio, unless MK_TEST_NO_EXTRA=1 marks a deliberate no-extra run
    import wiki_studio.api as api
except ImportError:
    if os.environ.get(NO_EXTRA_ENV) == "1":
        pytest.skip("deliberate no-extra run", allow_module_level=True)
    raise

DECISION = "Use Postgres for the user DB\n\nBecause of concurrent writes."
OTHER = "Use arq for background jobs\n\nBecause it is async-native."
DECISION_PAGE = "decisions/use-postgres-for-the-user-db.md"


def _exporter(root: Path, *decisions: str) -> WikiExporter:
    svc = _service()
    for text in decisions:
        svc.retain(text, MemoryType.DECISION)
    return WikiExporter(svc, root / "wiki", project_root=root)


def _another_writer(
    svc: MemoryService, root: Path, text: str, name: str, promote: Callable[..., Any] = api.promote
) -> tuple[str, bytes]:
    """Create one decision page plus its index line through wiki-studio itself; return its path and bytes."""
    from wiki_studio.paths import WikiPaths

    helper = WikiExporter(svc, root / "wiki", project_root=root)
    memory = svc.get(svc.retain(text, MemoryType.DECISION))
    assert memory is not None
    page = helper._page_for(memory, "decision")
    rel = f"decisions/{page.slug}.md"
    content = render_page(page)
    edits = [
        api.PageEdit(path=rel, action="create", new_content=content, rationale="another writer"),
        api.PageEdit(path="index.md", action="append-index", new_content=helper._index_line(rel, page), rationale="x"),
    ]
    paths = WikiPaths.for_root(root, wiki_dir=root / "wiki", proposals_dir=root / DEFAULT_PROPOSALS_SUBDIR)
    api.init(paths)
    promote(api.propose(edits, paths, name=name, source="another writer"), paths)
    return rel, content.encode("utf-8")


def _interleave(
    monkeypatch: pytest.MonkeyPatch,
    before_promote: Callable[[Callable[..., Any]], None],
    raised: list[BaseException] | None = None,
) -> list[Path]:
    """Run ``before_promote(real_promote)`` between memkernel's propose and its promote; return what it promoted.

    What memkernel's promote raised is appended to ``raised`` when given.
    """
    real = api.promote
    calls: list[Path] = []

    def promote(proposal: Path, paths: Any, **kwargs: Any) -> Any:
        calls.append(proposal)
        before_promote(real)
        try:
            return real(proposal, paths, **kwargs)
        except BaseException as exc:
            if raised is not None:
                raised.append(exc)
            raise

    monkeypatch.setattr(api, "promote", promote)
    return calls


def _applied(root: Path) -> list[str]:
    applied = root / DEFAULT_PROPOSALS_SUBDIR / ".applied"
    return sorted(p.name for p in applied.iterdir() if not p.name.startswith(".")) if applied.is_dir() else []


# ── SC-1: compatibility ───────────────────────────────────────────────────────


def test_a_page_another_writer_creates_after_planning_is_refused_once_and_kept(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    exporter = _exporter(tmp_path, DECISION)
    other_svc = _service()
    taken: dict[str, bytes] = {}

    def create_the_same_page(real: Callable[..., Any]) -> None:
        rel, content = _another_writer(other_svc, tmp_path, DECISION, "curator-1", real)
        taken[rel] = content

    raised: list[BaseException] = []
    calls = _interleave(monkeypatch, create_the_same_page, raised)
    report = exporter.export()

    from wiki_studio.errors import PromoteValidationError

    assert len(calls) == 1  # refused, not retried
    assert len(raised) == 1 and isinstance(raised[0], PromoteValidationError)
    assert PromoteValidationError.exit_code == 9  # the CLI's "create of an existing page" refusal
    assert report.gated is False and report.written == []
    assert report.gate_error is not None and DECISION_PAGE in report.gate_error
    assert (tmp_path / "wiki" / DECISION_PAGE).read_bytes() == taken[DECISION_PAGE]  # the other writer's page
    assert _applied(tmp_path) == ["curator-1"]


def test_creates_and_appends_land_through_propose_and_promote(tmp_path: Path) -> None:
    report = _exporter(tmp_path, DECISION, OTHER).export()

    assert report.gated is True and report.gate_error is None and len(report.written) == 2
    index = (tmp_path / "wiki" / "index.md").read_text(encoding="utf-8")
    assert all(f"]({rel})" in index for rel in report.written)
    assert report.proposal is not None and _applied(tmp_path) == [report.proposal]


# ── SC-2: concurrency ─────────────────────────────────────────────────────────


def test_another_promote_during_an_export_lands_and_neither_is_reverted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    exporter = _exporter(tmp_path, DECISION)
    other_svc = _service()
    theirs: dict[str, bytes] = {}

    def create_another_page(real: Callable[..., Any]) -> None:
        if not theirs:
            rel, content = _another_writer(other_svc, tmp_path, OTHER, "curator-1", real)
            theirs[rel] = content

    _interleave(monkeypatch, create_another_page)
    report = exporter.export()

    assert report.gated is True and report.written == [DECISION_PAGE]
    ((their_rel, their_bytes),) = theirs.items()
    wiki = tmp_path / "wiki"
    assert (wiki / their_rel).read_bytes() == their_bytes
    assert (wiki / DECISION_PAGE).is_file()
    index = (wiki / "index.md").read_text(encoding="utf-8")
    assert f"]({their_rel})" in index and f"]({DECISION_PAGE})" in index
    assert _applied(tmp_path) == sorted(["curator-1", str(report.proposal)])


# ── SC-3: forced failure ──────────────────────────────────────────────────────


def _files(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*.md"))}


def test_a_forced_failure_changes_no_file_another_writer_committed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _another_writer(_service(), tmp_path, OTHER, "curator-1")
    wiki = tmp_path / "wiki"
    before = _files(wiki)
    target = (wiki / DECISION_PAGE).resolve()
    original = Path.write_bytes

    def half_write(self: Path, data: bytes) -> int:
        if self.resolve() == target:
            original(self, data[: len(data) // 2])
            raise OSError(28, "No space left on device")
        return original(self, data)

    monkeypatch.setattr(Path, "write_bytes", half_write)
    report = _exporter(tmp_path, DECISION).export()

    assert report.gate_error is not None and "No space left on device" in report.gate_error
    assert report.written == [] and report.gated is False and report.proposal is None
    assert _files(wiki) == before  # the other writer's page, index.md and log.md byte for byte; no new page


def test_a_failed_export_never_reverts_a_page_another_writer_committed_during_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The mixed-writer hazard behind memkernel #48: a whole-wiki restore would delete the other writer's page."""
    _another_writer(_service(), tmp_path, "Deploy with blue-green releases", "curator-0")
    exporter = _exporter(tmp_path, DECISION)
    other_svc = _service()
    theirs: dict[str, bytes] = {}

    def create_another_page(real: Callable[..., Any]) -> None:
        rel, content = _another_writer(other_svc, tmp_path, OTHER, "curator-1", real)
        theirs[rel] = content

    _interleave(monkeypatch, create_another_page)
    wiki = tmp_path / "wiki"
    target = (wiki / DECISION_PAGE).resolve()
    original = Path.write_bytes

    def fail_memkernels_page(self: Path, data: bytes) -> int:
        if self.resolve() == target:
            raise OSError(5, "Input/output error")
        return original(self, data)

    monkeypatch.setattr(Path, "write_bytes", fail_memkernels_page)
    report = exporter.export()

    assert report.gate_error is not None and report.written == []
    ((their_rel, their_bytes),) = theirs.items()
    assert (wiki / their_rel).read_bytes() == their_bytes
    assert f"]({their_rel})" in (wiki / "index.md").read_text(encoding="utf-8")
    assert not (wiki / DECISION_PAGE).exists()


def test_a_failed_export_to_a_new_wiki_leaves_only_the_scaffold_init_created(tmp_path: Path) -> None:
    from memkernel.wiki import sync

    with pytest.MonkeyPatch.context() as m:  # a decision page in concepts/ violates the schema
        m.setitem(sync.EXPORT_MAP, MemoryType.DECISION, ("decision", "concepts"))
        report = _exporter(tmp_path, DECISION).export()

    assert report.gate_error is not None and report.written == []
    assert sorted(_files(tmp_path / "wiki")) == ["index.md", "log.md"]


# ── SC-4: an older wiki-studio is refused ─────────────────────────────────────


def test_an_older_wiki_studio_is_refused_and_nothing_is_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from importlib import metadata

    monkeypatch.setattr(metadata, "version", lambda name: "0.5.0")
    report = _exporter(tmp_path, DECISION).export()

    assert report.gate_error is not None and "wiki-studio 0.5.0" in report.gate_error
    assert ">= 0.7.0" in report.gate_error
    assert report.written == [] and report.skipped == 1 and not (tmp_path / "wiki").exists()


@pytest.mark.parametrize("call", ["init", "review_state", "read_page"])
def test_a_wiki_studio_without_a_call_the_bridge_makes_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, call: str
) -> None:
    monkeypatch.delattr(api, call)
    report = _exporter(tmp_path, DECISION).export()

    assert report.gate_error is not None and f"missing {call}" in report.gate_error
    assert report.written == [] and not (tmp_path / "wiki").exists()


# ── SC-6 and FR-005: the receipt ──────────────────────────────────────────────


def _receipt_digest(directory: Path) -> str:
    import json

    return str(json.loads((directory / "receipt.json").read_text(encoding="utf-8"))["submission_digest"])


def test_a_promoted_export_reports_its_proposal_and_receipt(tmp_path: Path) -> None:
    report = _exporter(tmp_path, DECISION).export()

    assert report.gated is True and report.proposal is not None
    assert report.proposal.startswith("memkernel-export-")
    assert report.archived_dir is not None and Path(report.archived_dir).name == report.proposal
    assert report.submission_digest == _receipt_digest(Path(report.archived_dir))
    assert report.archive_hint is None and report.receipt_error is None


@pytest.mark.skipif(hasattr(os, "geteuid") and os.geteuid() == 0, reason="root ignores directory permissions")
def test_an_unarchived_export_reports_the_command_that_finishes_it(tmp_path: Path) -> None:
    applied = tmp_path / DEFAULT_PROPOSALS_SUBDIR / ".applied"
    applied.mkdir(parents=True)
    applied.chmod(0o500)  # wiki-studio commits, then cannot archive (its step 4 treats OSError as housekeeping)
    try:
        report = _exporter(tmp_path, DECISION).export()
    finally:
        applied.chmod(0o700)

    assert report.gated is True and report.gate_error is None and report.written == [DECISION_PAGE]
    assert report.archived_dir is None and report.receipt_error is None
    proposal_dir = tmp_path / DEFAULT_PROPOSALS_SUBDIR / str(report.proposal)
    assert report.submission_digest == _receipt_digest(proposal_dir)
    assert report.archive_hint is not None and str(proposal_dir) in report.archive_hint

    pages = _files(tmp_path / "wiki")
    command = shlex.split(report.archive_hint.split("to finish, run: ", 1)[1].split(" (it finishes", 1)[0])
    finished = subprocess.run(command, capture_output=True, text=True, check=False)  # noqa: S603

    assert finished.returncode == 0, finished.stderr
    assert not proposal_dir.exists() and _applied(tmp_path) == [report.proposal]
    assert _files(tmp_path / "wiki") == pages  # finishing the archive applied nothing twice


@pytest.mark.skipif(hasattr(os, "geteuid") and os.geteuid() == 0, reason="root ignores directory permissions")
def test_the_archive_hint_works_from_any_directory_with_relative_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """MEMKERNEL_PROJECT_ROOT defaults to "." and the README's wiki is knowledge/wiki: the hint must be absolute."""
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.chdir(project)
    svc = _service()
    svc.retain(DECISION, MemoryType.DECISION)
    applied = project / DEFAULT_PROPOSALS_SUBDIR / ".applied"
    applied.mkdir(parents=True)
    applied.chmod(0o500)
    try:
        report = WikiExporter(svc, Path("knowledge") / "wiki", project_root=Path(".")).export()
    finally:
        applied.chmod(0o700)

    assert report.archived_dir is None and report.archive_hint is not None
    command = shlex.split(report.archive_hint.split("to finish, run: ", 1)[1].split(" (it finishes", 1)[0])
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    finished = subprocess.run(command, capture_output=True, text=True, check=False, cwd=elsewhere)  # noqa: S603

    assert finished.returncode == 0, finished.stderr
    assert _applied(project) == [report.proposal]


@pytest.mark.skipif(hasattr(os, "geteuid") and os.geteuid() == 0, reason="root ignores directory permissions")
@pytest.mark.parametrize("content", ["not json", "[]", "{}", '{"submission_digest": 7}'])
def test_an_unusable_receipt_left_in_the_proposal_directory_is_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, content: str
) -> None:
    original = Path.read_text

    def read_text(self: Path, *args: Any, **kwargs: Any) -> str:
        if self.name == "receipt.json" and ".applied" not in self.parts:
            return content
        return original(self, *args, **kwargs)

    applied = tmp_path / DEFAULT_PROPOSALS_SUBDIR / ".applied"
    applied.mkdir(parents=True)
    applied.chmod(0o500)
    monkeypatch.setattr(Path, "read_text", read_text)
    try:
        report = _exporter(tmp_path, DECISION).export()
    finally:
        applied.chmod(0o700)

    assert report.gated is True and report.written == [DECISION_PAGE] and report.gate_error is None
    assert report.archived_dir is None and report.archive_hint is not None
    assert report.submission_digest is None and report.receipt_error is not None


# ── SC-7 and FR-009: committed, then failed ───────────────────────────────────


def _fail_the_committed_receipt(monkeypatch: pytest.MonkeyPatch) -> None:
    """wiki-studio commits the pages, then cannot rewrite its receipt as committed (its step 3)."""
    from wiki_studio import promoter

    real = promoter._write_receipt
    calls = [0]

    def write_receipt(proposals_dir: Path, receipt: dict[str, Any]) -> bytes:
        calls[0] += 1
        if calls[0] == 2:
            raise OSError(28, "No space left on device")
        return real(proposals_dir, receipt)

    monkeypatch.setattr(promoter, "_write_receipt", write_receipt)


def _run_hint(hint: str) -> subprocess.CompletedProcess[str]:
    command = shlex.split(hint.split("to finish, run: ", 1)[1].split(" (it finishes", 1)[0])
    return subprocess.run(command, capture_output=True, text=True, check=False)  # noqa: S603


def test_an_export_committed_before_wiki_studio_failed_is_reported_as_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fail_the_committed_receipt(monkeypatch)
    report = _exporter(tmp_path, DECISION).export()

    assert report.gated is True and report.written == [DECISION_PAGE] and report.skipped == 0
    assert report.gate_error is None and report.archived_dir is None and report.receipt_error is None
    proposal_dir = tmp_path / DEFAULT_PROPOSALS_SUBDIR / str(report.proposal)
    assert report.submission_digest == _receipt_digest(proposal_dir)
    assert report.archive_hint is not None and "committed the export, then failed" in report.archive_hint

    monkeypatch.undo()  # the user's own promote runs without the forced failure
    pages = _files(tmp_path / "wiki")
    finished = _run_hint(report.archive_hint)
    assert finished.returncode == 0, finished.stderr
    assert not proposal_dir.exists() and _applied(tmp_path) == [report.proposal]
    assert _files(tmp_path / "wiki") == pages  # finishing applied nothing twice


def test_a_refusal_before_any_receipt_is_a_gate_error_even_with_identical_bytes_on_disk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two exports of one store at once: the second is refused (create of an existing page) before wiki-studio
    writes a receipt, while the first export's identical page is on disk. No receipt means no commit."""
    svc = _service()
    svc.retain(DECISION, MemoryType.DECISION)
    first: list[Any] = []

    def the_other_export_lands_first(real: Callable[..., Any]) -> None:
        if not first:
            with pytest.MonkeyPatch.context() as m:
                m.setattr(api, "promote", real)
                first.append(WikiExporter(svc, tmp_path / "wiki", project_root=tmp_path).export())

    _interleave(monkeypatch, the_other_export_lands_first)
    report = WikiExporter(svc, tmp_path / "wiki", project_root=tmp_path).export()

    assert first[0].gated is True and first[0].written == [DECISION_PAGE]
    assert report.gate_error is not None and "already exists" in report.gate_error
    assert report.gated is False and report.written == [] and report.archive_hint is None


def test_a_receipt_that_does_not_record_a_commit_is_a_gate_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The receipt's state is part of wiki-studio's record: one that is neither committing nor committed decides."""
    import json

    _fail_the_committed_receipt(monkeypatch)
    original = Path.read_text

    def read_text(self: Path, *args: Any, **kwargs: Any) -> str:
        text = original(self, *args, **kwargs)
        if self.name == "receipt.json":
            return json.dumps({**json.loads(text), "state": "planned"})
        return text

    monkeypatch.setattr(Path, "read_text", read_text)
    report = _exporter(tmp_path, DECISION).export()

    assert report.gate_error is not None and report.written == [] and report.gated is False


def test_without_a_usable_receipt_the_pages_bytes_decide(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _fail_the_committed_receipt(monkeypatch)
    original = Path.read_text

    def read_text(self: Path, *args: Any, **kwargs: Any) -> str:
        if self.name == "receipt.json":
            raise OSError(5, "Input/output error")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read_text)
    report = _exporter(tmp_path, DECISION).export()

    assert report.gated is True and report.written == [DECISION_PAGE] and report.gate_error is None
    assert report.submission_digest is None and report.archived_dir is None
    assert report.receipt_error is not None and "Input/output error" in report.receipt_error
    assert report.archive_hint is not None


def test_an_unreadable_receipt_is_reported_and_never_fails_the_export(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = Path.read_text

    def read_text(self: Path, *args: Any, **kwargs: Any) -> str:
        if self.name == "receipt.json" and ".applied" in self.parts:
            raise OSError(5, "Input/output error")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read_text)
    report = _exporter(tmp_path, DECISION).export()

    assert report.gated is True and report.written == [DECISION_PAGE] and report.gate_error is None
    assert report.submission_digest is None and report.archived_dir is not None
    assert report.receipt_error is not None and "Input/output error" in report.receipt_error

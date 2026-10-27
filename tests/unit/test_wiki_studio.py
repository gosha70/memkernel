# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""The optional wiki-studio integration (memkernel[wiki], ADR-010): lint on export, silent absence."""

from __future__ import annotations

import logging
import sys
import tomllib
import types
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from memkernel.config import MemKernelSettings
from memkernel.core.models import MemoryType
from memkernel.wiki.studio import (
    GATE_MIN_VERSION,
    INSTALL_HINT,
    GateError,
    LintError,
    LintSummary,
    _release,
    gate_available,
    lint_wiki,
    load_studio,
)
from memkernel.wiki.sync import WikiExporter
from tests.unit.test_wiki import _service

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = pytest.mark.unit

PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"


class _AbsentPackage:
    """Meta-path finder that makes ``wiki_studio`` fail exactly like an uninstalled package."""

    def find_spec(self, name: str, path: object = None, target: object = None) -> None:
        if name == "wiki_studio":
            raise ModuleNotFoundError(f"No module named {name!r}", name=name)
        return None


@pytest.fixture
def no_wiki_studio(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Simulate the extra being absent: importing wiki_studio raises ModuleNotFoundError(name="wiki_studio")."""
    for name in list(sys.modules):
        if name == "wiki_studio" or name.startswith("wiki_studio."):
            monkeypatch.delitem(sys.modules, name)
    monkeypatch.setattr(sys, "meta_path", [_AbsentPackage(), *sys.meta_path])
    yield


def _export_three(wiki_dir: Path, project_root: Path) -> WikiExporter:
    svc = _service()
    svc.retain("Use Postgres for the user DB\n\nBecause of concurrent writes.", MemoryType.DECISION)
    svc.retain("All services log JSON to stdout; never write log files.", MemoryType.CONVENTION)
    svc.retain("Run `make verify` before every PR.", MemoryType.PROCEDURE)
    return WikiExporter(svc, wiki_dir, project_root=project_root)


def test_export_reports_lint_and_health_with_the_extra(tmp_path: Path) -> None:
    pytest.importorskip("wiki_studio.api")
    report = _export_three(tmp_path / "knowledge" / "wiki", tmp_path).export()

    assert len(report.written) == 3
    assert isinstance(report.lint, LintSummary)
    assert report.lint.violations == []
    assert report.lint.audit_errors == []
    assert report.lint.pages_checked == 5  # three pages plus index.md and log.md
    assert report.lint.health is not None
    assert {item.kind for item in report.lint.health} <= {"weak-orphan"}
    for item in report.lint.health:  # wiki-studio's HealthFinding shape, field for field
        assert item.severity and isinstance(item.pages, list) and item.pages and item.description


def test_export_without_the_extra_writes_the_same_files_and_is_silent(
    tmp_path: Path, no_wiki_studio: None, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.WARNING, logger="memkernel.wiki.studio")
    wiki_dir = tmp_path / "knowledge" / "wiki"

    report = _export_three(wiki_dir, tmp_path).export()

    assert len(report.written) == 3
    assert report.lint is None
    assert (wiki_dir / "index.md").is_file() and (wiki_dir / "log.md").is_file()
    assert not caplog.records  # absence of an optional extra is not worth a log line


def test_missing_extra_warns_only_when_required(no_wiki_studio: None, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING, logger="memkernel.wiki.studio")

    assert load_studio() is None
    assert not caplog.records

    assert load_studio(require_studio=True) is None
    assert [r.levelno for r in caplog.records] == [logging.WARNING]
    assert INSTALL_HINT in caplog.text


def test_lint_wiki_without_the_extra_returns_none(tmp_path: Path, no_wiki_studio: None) -> None:
    assert lint_wiki(tmp_path / "wiki", tmp_path) is None


def test_wiki_studio_is_declared_only_as_an_optional_extra() -> None:
    """SC-1: `pip install memkernel` pulls nothing new; the extra pulls wiki-studio only."""
    with PYPROJECT.open("rb") as fh:
        pyproject = tomllib.load(fh)
    poetry = pyproject["tool"]["poetry"]

    assert poetry["dependencies"]["wiki-studio"]["optional"] is True
    assert poetry["extras"] == {"wiki": ["wiki-studio"]}
    floor = ".".join(str(part) for part in GATE_MIN_VERSION)  # the extra's floor is the gate's floor
    assert poetry["dependencies"]["wiki-studio"]["version"] == f">={floor},<1"
    assert poetry["group"]["dev"]["dependencies"]["wiki-studio"] == f">={floor},<1"


@pytest.mark.parametrize(
    ("version", "release"),
    [("0.6.0", (0, 6, 0)), ("0.6.0rc1", (0, 6, 0)), ("0.10.2.post1", (0, 10, 2)), ("1", (1,)), ("unknown", ())],
)
def test_release_reads_the_leading_numeric_version(version: str, release: tuple[int, ...]) -> None:
    assert _release(version) == release


def test_a_wiki_studio_whose_version_cannot_be_read_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("wiki_studio.api")
    from importlib import metadata

    def missing(name: str) -> str:
        raise metadata.PackageNotFoundError(name)

    monkeypatch.setattr(metadata, "version", missing)
    with pytest.raises(GateError, match="wiki-studio unknown is installed"):
        gate_available()


def test_lint_failure_never_fails_the_export(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A wiki-studio error after the pages are written is reported, not raised (finding: export already succeeded)."""
    api = pytest.importorskip("wiki_studio.api")
    caplog.set_level(logging.WARNING, logger="memkernel.wiki.studio")

    def boom(*args: object, **kwargs: object) -> object:
        raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "curated page is not UTF-8")

    monkeypatch.setattr(api, "lint", boom)
    wiki_dir = tmp_path / "knowledge" / "wiki"

    report = _export_three(wiki_dir, tmp_path).export()

    assert len(report.written) == 3
    assert (wiki_dir / "index.md").is_file() and (wiki_dir / "log.md").is_file()
    assert report.lint is None
    assert report.lint_error is not None and "wiki-studio lint failed" in report.lint_error
    assert [r.levelno for r in caplog.records] == [logging.WARNING]
    with pytest.raises(LintError):
        lint_wiki(wiki_dir, tmp_path)


def test_lint_accepts_an_empty_project_root_from_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """MEMKERNEL_PROJECT_ROOT="" reaches the exporter as the empty string the tool turns into Path("")."""
    pytest.importorskip("wiki_studio.api")
    monkeypatch.chdir(tmp_path)
    settings = MemKernelSettings(project_root="", chroma_persist_path="")
    wiki_dir = tmp_path / "knowledge" / "wiki"

    report = _export_three(wiki_dir, Path(settings.project_root)).export()

    assert report.lint is not None and report.lint.violations == []


def test_broken_installation_is_reported_not_treated_as_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A present but broken wiki_studio package is a gate error (nothing written) and a lint error, never absence."""
    caplog.set_level(logging.WARNING, logger="memkernel.wiki.studio")
    for name in list(sys.modules):
        if name == "wiki_studio" or name.startswith("wiki_studio."):
            monkeypatch.delitem(sys.modules, name)
    stub = types.ModuleType("wiki_studio")
    stub.__path__ = []  # a package whose submodule import fails
    monkeypatch.setitem(sys.modules, "wiki_studio", stub)
    monkeypatch.setitem(sys.modules, "wiki_studio.api", None)

    with pytest.raises(LintError, match="installed but broken"):
        load_studio()

    wiki_dir = tmp_path / "knowledge" / "wiki"
    caplog.clear()
    report = _export_three(wiki_dir, tmp_path).export()
    assert report.written == [] and report.skipped == 3 and report.gated is False
    assert report.gate_error is not None and "installed but broken" in report.gate_error
    assert not wiki_dir.exists()  # no pages and no scaffold: the broken validator let nothing through
    assert report.lint is None
    assert report.lint_error is not None and "installed but broken" in report.lint_error
    assert [r.levelno for r in caplog.records] == [logging.WARNING]  # logged exactly once


def test_unrecognised_result_shape_is_a_lint_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """An incompatible wiki-studio whose findings lack a field fails the lint, not the export."""
    api = pytest.importorskip("wiki_studio.api")

    class Finding:
        kind = "weak-orphan"
        severity = "warning"
        description = "no pages attribute"

    class Health:
        findings = [Finding()]

    class Result:
        violations = ()
        audit_errors = ()
        pages_checked = 1
        health = Health()

    monkeypatch.setattr(api, "lint", lambda *args, **kwargs: Result())
    wiki_dir = tmp_path / "knowledge" / "wiki"

    report = _export_three(wiki_dir, tmp_path).export()

    assert len(report.written) == 3 and (wiki_dir / "index.md").is_file()
    assert report.lint is None
    assert report.lint_error is not None and "wiki-studio lint failed" in report.lint_error


class _FailingInit:
    """Meta-path finder whose ``wiki_studio`` package raises RuntimeError while it initialises."""

    def find_spec(self, name: str, path: object = None, target: object = None) -> object:
        if name != "wiki_studio":
            return None
        import importlib.machinery

        class Loader:
            def create_module(self, spec: object) -> None:
                return None

            def exec_module(self, module: object) -> None:
                raise RuntimeError("wiki-studio failed to initialise")

        return importlib.machinery.ModuleSpec(name, Loader(), is_package=True)


def test_initialisation_error_is_a_lint_error_logged_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A non-ImportError raised while wiki_studio initialises is reported, not raised, and writes nothing."""
    caplog.set_level(logging.WARNING, logger="memkernel.wiki.studio")
    for name in list(sys.modules):
        if name == "wiki_studio" or name.startswith("wiki_studio."):
            monkeypatch.delitem(sys.modules, name)
    monkeypatch.setattr(sys, "meta_path", [_FailingInit(), *sys.meta_path])
    wiki_dir = tmp_path / "knowledge" / "wiki"

    report = _export_three(wiki_dir, tmp_path).export()

    assert report.written == [] and not wiki_dir.exists()
    assert report.gate_error is not None and "failed to initialise" in report.gate_error
    assert report.lint is None
    assert report.lint_error is not None and "failed to initialise" in report.lint_error
    assert [r.levelno for r in caplog.records] == [logging.WARNING]


# ── the promote gate (FR-007, SC-2) ───────────────────────────────────────────

FIXED_DAY = "2026-10-16"
WRITTEN = ("decisions", "concepts", "workflows")


def _written_files(wiki_dir: Path) -> dict[str, str]:
    """Pages, index.md and log.md (the gate's .audit/ is excluded)."""
    files = {}
    for path in sorted(wiki_dir.rglob("*.md")):
        rel = path.relative_to(wiki_dir).as_posix()
        if rel in ("index.md", "log.md") or rel.split("/")[0] in WRITTEN:
            files[rel] = path.read_text(encoding="utf-8")
    return files


def _pages_and_entries(wiki_dir: Path) -> dict[str, object]:
    """What memkernel-0-5 SC-2 compares since memkernel-0-6 FR-002: pages, and the index and log entry lines."""
    files = _written_files(wiki_dir)
    entries = {
        name: [ln for ln in files.pop(name, "").splitlines() if ln.startswith("- ")] for name in ("index.md", "log.md")
    }
    return {**files, **entries}


def _pages(wiki_dir: Path) -> dict[str, str]:
    return {rel: text for rel, text in _written_files(wiki_dir).items() if rel not in ("index.md", "log.md")}


@pytest.fixture
def fixed_day(monkeypatch: pytest.MonkeyPatch) -> None:
    from memkernel.wiki import sync

    monkeypatch.setattr(sync, "_today", lambda: FIXED_DAY)


def test_gated_export_matches_the_direct_writer_in_pages_and_entries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fixed_day: None
) -> None:
    pytest.importorskip("wiki_studio.api")
    from memkernel.wiki import sync

    gated_wiki, direct_wiki = tmp_path / "gated" / "wiki", tmp_path / "direct" / "wiki"
    exporter = _export_three(gated_wiki, tmp_path / "gated")  # one store, so both wikis cite the same ref_ids
    gated = exporter.export()
    monkeypatch.setattr(sync, "gate_available", lambda: None)
    direct = WikiExporter(exporter._service, direct_wiki, project_root=tmp_path / "direct").export()

    assert gated.gated is True and direct.gated is False and gated.gate_error is None
    assert gated.written == direct.written and len(gated.written) == 3
    assert _pages_and_entries(gated_wiki) == _pages_and_entries(direct_wiki)
    # the scaffold of a new wiki is wiki-studio's on the gated path, memkernel's on the direct one (FR-002)
    assert "title: Wiki\nstatus: stable" in (gated_wiki / "index.md").read_text(encoding="utf-8")
    assert "title: Wiki Index\nstatus: draft" in (direct_wiki / "index.md").read_text(encoding="utf-8")
    assert (gated_wiki / ".audit" / "proposals").is_dir()  # the gate's own trail, outside the comparison


def test_the_proposals_directory_is_explicit_or_memkernels_default(tmp_path: Path) -> None:
    pytest.importorskip("wiki_studio.api")
    svc_dir = tmp_path / "explicit"
    exporter = _export_three(svc_dir / "wiki", svc_dir)
    exporter._proposals_dir = svc_dir / "props"  # what the tool passes from MEMKERNEL_WIKI_PROPOSALS_DIR
    assert exporter.export().gated
    assert any((svc_dir / "props" / ".applied").iterdir())

    default_dir = tmp_path / "default"
    assert _export_three(default_dir / "wiki", default_dir).export().gated
    assert any((default_dir / ".memkernel" / "wiki-proposals" / ".applied").iterdir())


SCHEMA_REJECTION = "page_type 'decision' should live under decisions/"


def test_a_rejected_export_leaves_pages_index_and_log_as_they_were(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fixed_day: None
) -> None:
    pytest.importorskip("wiki_studio.api")
    from memkernel.wiki import sync

    # A decision page placed in concepts/ violates the schema; the gate refuses the whole patch-set.
    monkeypatch.setitem(sync.EXPORT_MAP, MemoryType.DECISION, ("decision", "concepts"))

    fresh = tmp_path / "fresh" / "wiki"
    report = _export_three(fresh, tmp_path / "fresh").export()
    assert report.gate_error is not None and SCHEMA_REJECTION in report.gate_error  # rejected for the schema
    assert report.written == [] and report.gated is False
    assert _pages_and_entries(fresh) == {"index.md": [], "log.md": []}  # only the empty scaffold init created

    # A wiki that already took one clean export: every link resolves, so only the schema can reject.
    monkeypatch.setitem(sync.EXPORT_MAP, MemoryType.DECISION, ("decision", "decisions"))
    existing, exporter = _curated_wiki(tmp_path / "existing")
    monkeypatch.setitem(sync.EXPORT_MAP, MemoryType.DECISION, ("decision", "concepts"))
    before = _files(existing)
    report = exporter.export()
    assert report.gate_error is not None and SCHEMA_REJECTION in report.gate_error
    assert "Structural linter" not in report.gate_error
    assert _files(existing) == before


def test_without_the_gate_the_direct_writer_runs_and_only_a_requested_gate_warns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, no_wiki_studio: None, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.WARNING, logger="memkernel.wiki.studio")

    plain = _export_three(tmp_path / "plain" / "wiki", tmp_path / "plain").export()
    assert plain.gated is False and len(plain.written) == 3
    assert not caplog.records  # absence of the extra is silent

    asked = WikiExporter(
        _service(), tmp_path / "asked" / "wiki", project_root=tmp_path, proposals_dir=tmp_path / "props"
    )
    asked.export()
    assert [r.levelno for r in caplog.records] == [logging.WARNING]  # MEMKERNEL_WIKI_PROPOSALS_DIR set, no gate
    assert INSTALL_HINT in caplog.text


def test_export_without_index_updates_takes_the_direct_writer(tmp_path: Path) -> None:
    """Pages without index entries are orphans, which the gate rejects by design."""
    pytest.importorskip("wiki_studio.api")
    report = _export_three(tmp_path / "wiki", tmp_path).export(update_index=False)
    assert report.gated is False and len(report.written) == 3
    assert not (tmp_path / "wiki" / "index.md").exists() and not (tmp_path / "wiki" / ".audit").exists()


def test_bypassing_a_requested_gate_with_update_index_false_warns(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    pytest.importorskip("wiki_studio.api")
    caplog.set_level(logging.WARNING, logger="memkernel.wiki.sync")
    exporter = WikiExporter(_service(), tmp_path / "wiki", project_root=tmp_path, proposals_dir=tmp_path / "props")
    exporter._service.retain("Use arq for background jobs", MemoryType.DECISION)

    report = exporter.export(update_index=False)

    assert report.gated is False and report.written
    assert [r.levelno for r in caplog.records] == [logging.WARNING]
    assert "bypasses it" in caplog.text

    caplog.clear()
    quiet = WikiExporter(_service(), tmp_path / "wiki2", project_root=tmp_path)  # gate not requested
    quiet._service.retain("Use arq for background jobs", MemoryType.DECISION)
    quiet.export(update_index=False)
    assert not caplog.records


def test_a_broken_installation_with_a_requested_gate_and_nothing_to_export_does_not_raise(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in list(sys.modules):
        if name == "wiki_studio" or name.startswith("wiki_studio."):
            monkeypatch.delitem(sys.modules, name)
    monkeypatch.setattr(sys, "meta_path", [_FailingInit(), *sys.meta_path])
    exporter = WikiExporter(_service(), tmp_path / "wiki", project_root=tmp_path, proposals_dir=tmp_path / "props")

    report = exporter.export()

    assert report.written == [] and report.gate_error is None
    assert report.lint_error is not None and "failed to initialise" in report.lint_error


def test_a_gate_setup_failure_is_a_gate_error_and_removes_the_scaffold_it_created(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fixed_day: None
) -> None:
    api = pytest.importorskip("wiki_studio.api")
    from memkernel.wiki import sync

    def broken_edit(*args: object, **kwargs: object) -> None:
        raise RuntimeError("PageEdit exploded")

    monkeypatch.setattr(api, "PageEdit", broken_edit)

    fresh = tmp_path / "fresh" / "wiki"
    report = _export_three(fresh, tmp_path / "fresh").export()
    assert report.gate_error is not None and "PageEdit exploded" in report.gate_error
    assert report.written == [] and report.gated is False
    assert not (fresh / "index.md").exists() and not (fresh / "log.md").exists()
    assert _written_files(fresh) == {}

    existing = tmp_path / "existing" / "wiki"
    existing.mkdir(parents=True)
    (existing / "index.md").write_text(sync._index_scaffold(), encoding="utf-8")
    (existing / "log.md").write_text(sync._log_scaffold(), encoding="utf-8")
    before = _written_files(existing)
    assert _export_three(existing, tmp_path / "existing").export().gate_error is not None
    assert _written_files(existing) == before  # a scaffold this call did not create is kept as it was


def _fail_writes(
    monkeypatch: pytest.MonkeyPatch, wiki_dir: Path, rel: str, exc: Exception, *, partial: bool, times: int = 1
) -> None:
    """Make the next ``times`` writes (text or bytes) of ``wiki_dir/rel`` fail, a text one after writing half."""
    original = Path.write_text
    target = (wiki_dir / rel).resolve()
    remaining = [times]

    def write_text(self: Path, data: str, *args: object, **kwargs: object) -> int:
        if remaining[0] and self.resolve() == target:
            remaining[0] -= 1
            if partial:
                original(self, data[: len(data) // 2], *args, **kwargs)  # type: ignore[arg-type]
            raise exc
        return original(self, data, *args, **kwargs)  # type: ignore[arg-type]

    original_bytes = Path.write_bytes

    def write_bytes(self: Path, data: bytes) -> int:
        if remaining[0] and self.resolve() == target:
            remaining[0] -= 1
            raise exc
        return original_bytes(self, data)

    monkeypatch.setattr(Path, "write_text", write_text)
    monkeypatch.setattr(Path, "write_bytes", write_bytes)


def _files(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def _curated_wiki(tmp_path: Path) -> tuple[Path, WikiExporter]:
    """A wiki that already went through one clean gated export, and an exporter with one more page to add."""
    wiki = tmp_path / "wiki"
    first = _export_three(wiki, tmp_path)
    assert first.export().gated
    first._service.retain("Use arq for background jobs\n\nBecause it is async-native.", MemoryType.DECISION)
    return wiki, first


def _gate_reached_the_write(caplog: pytest.LogCaptureFixture) -> bool:
    return "live wiki write failed" in caplog.text or "not an OSError" in caplog.text


@pytest.mark.parametrize(
    "exc", [OSError(28, "No space left on device"), ValueError("not an OSError")], ids=["oserror", "other"]
)
def test_a_promote_that_fails_part_way_through_a_page_write_leaves_a_new_wiki_only_its_scaffold(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, fixed_day: None, exc: Exception
) -> None:
    """wiki-studio >= 0.6.0 rolls back a write that failed part-way, on any exception; memkernel restores nothing."""
    pytest.importorskip("wiki_studio.api")
    caplog.set_level(logging.WARNING, logger="memkernel.wiki.studio")
    wiki = tmp_path / "wiki"
    exporter = _export_three(wiki, tmp_path)
    with monkeypatch.context() as m:
        _fail_writes(m, wiki, "decisions/use-postgres-for-the-user-db.md", exc, partial=True)
        report = exporter.export()

    assert _gate_reached_the_write(caplog)  # the failure happened while applying, not at validation
    assert report.gate_error is not None and report.written == [] and report.gated is False
    assert _pages_and_entries(wiki) == {"index.md": [], "log.md": []}  # no half-written page, no entry
    assert not (wiki / "decisions").exists() or not any((wiki / "decisions").iterdir())


@pytest.mark.parametrize("target", ["decisions/use-arq-for-background-jobs.md", "index.md"], ids=["page", "index"])
@pytest.mark.parametrize(
    "exc", [OSError(5, "Input/output error"), ValueError("not an OSError")], ids=["oserror", "other"]
)
def test_a_promote_that_fails_part_way_through_a_write_restores_a_curated_wiki(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    fixed_day: None,
    target: str,
    exc: Exception,
) -> None:
    pytest.importorskip("wiki_studio.api")
    caplog.set_level(logging.WARNING, logger="memkernel.wiki.studio")
    wiki, exporter = _curated_wiki(tmp_path)
    before = _files(wiki)
    with monkeypatch.context() as m:
        _fail_writes(m, wiki, target, exc, partial=True)
        report = exporter.export()

    assert _gate_reached_the_write(caplog)
    assert report.gate_error is not None and report.written == []
    assert _files(wiki) == before  # index.md byte for byte, no orphan page, no extra audit entry


def test_a_log_write_that_fails_is_a_gate_error_and_writes_no_page(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("wiki_studio.api")
    wiki = tmp_path / "wiki"
    exporter = _export_three(wiki, tmp_path)
    _fail_writes(monkeypatch, wiki, "log.md", PermissionError(13, "Permission denied"), partial=False)

    report = exporter.export()

    assert report.gate_error is not None and "Permission denied" in report.gate_error
    assert report.written == [] and report.skipped == 3
    assert _pages(wiki) == {}


def test_a_rollback_that_cannot_complete_is_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fixed_day: None
) -> None:
    pytest.importorskip("wiki_studio.api")
    wiki, exporter = _curated_wiki(tmp_path)
    with monkeypatch.context() as m:
        _fail_writes(m, wiki, "index.md", OSError(5, "Input/output error"), partial=True, times=10)
        report = exporter.export()

    assert report.gate_error is not None and report.written == []
    assert "rollback failed for index.md" in report.gate_error.lower()  # wiki-studio's own report, passed through


def test_an_index_that_is_not_utf8_is_a_gate_error(tmp_path: Path) -> None:
    pytest.importorskip("wiki_studio.api")
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    (wiki / "index.md").write_bytes(b"# Index\n\xff\xfe broken\n")
    before = _files(wiki)

    report = _export_three(wiki, tmp_path).export()

    assert report.gate_error is not None and "index.md" in report.gate_error
    assert report.written == [] and report.skipped == 3
    assert _files(wiki) == before

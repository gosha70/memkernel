# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""The optional wiki-studio integration (memkernel[wiki], ADR-010): lint on export, silent absence."""

from __future__ import annotations

import logging
import sys
import tomllib
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from memkernel.config import MemKernelSettings
from memkernel.core.models import MemoryType
from memkernel.wiki.studio import INSTALL_HINT, LintError, LintSummary, lint_wiki, load_studio
from memkernel.wiki.sync import WikiExporter
from tests.unit.test_wiki import _service

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = pytest.mark.unit

PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"


@pytest.fixture
def no_wiki_studio(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Simulate the extra being absent: importing wiki_studio raises ImportError."""
    for name in list(sys.modules):
        if name == "wiki_studio" or name.startswith("wiki_studio."):
            monkeypatch.delitem(sys.modules, name)
    monkeypatch.setitem(sys.modules, "wiki_studio", None)
    monkeypatch.setitem(sys.modules, "wiki_studio.api", None)
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

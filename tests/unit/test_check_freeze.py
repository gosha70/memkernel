# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""The 0.5.0 code-freeze verifier on a synthetic repository (FR-017, SC-8)."""

from __future__ import annotations

import importlib.util
import subprocess
from typing import TYPE_CHECKING

import pytest

from tests.unit._lifecycle_suite import REPO_ROOT

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit

_spec = importlib.util.spec_from_file_location("check_freeze", REPO_ROOT / "eval" / "check_freeze.py")
assert _spec is not None and _spec.loader is not None
check_freeze = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_freeze)

PREREG = "eval/lifecycle-suite/preregistration.md"
PREREG_COMMIT = "eval/lifecycle-suite/PREREG_COMMIT"


def _git(repo: Path, *args: str) -> str:
    env = {
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.com",
        "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
    }
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True, env=env
    ).stdout.strip()


def _write(repo: Path, rel: str, text: str) -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _commit(repo: Path, message: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture
def frozen(tmp_path: Path) -> tuple[Path, str, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _write(repo, "pyproject.toml", '[tool.poetry]\nname = "memkernel"\nversion = "0.5.0rc1"\n')
    _write(repo, "src/memkernel/__init__.py", '"""memkernel."""\n__version__ = "0.5.0rc1"\n')
    _write(repo, "src/memkernel/core.py", "X = 1\n")
    freeze = _commit(repo, "code freeze")
    _write(repo, PREREG, "# preregistration\n")
    prereg = _commit(repo, "preregistration")
    _write(repo, PREREG_COMMIT, prereg + "\n")
    _write(repo, "eval/lifecycle-suite/results/run1/receipts.jsonl", "{}\n")
    _write(repo, "eval/lifecycle-suite/report-0.5.0.md", "# report\n")
    _write(repo, "CHANGELOG.md", "## [0.5.0]\n")
    _write(repo, "pyproject.toml", '[tool.poetry]\nname = "memkernel"\nversion = "0.5.0"\n')
    _write(repo, "src/memkernel/__init__.py", '"""memkernel."""\n__version__ = "0.5.0"\n')
    _commit(repo, "results and release")
    return repo, freeze, prereg


def test_a_clean_release_passes(frozen: tuple[Path, str, str]) -> None:
    repo, freeze, _ = frozen
    assert check_freeze.check(repo, freeze) == []


def test_a_source_change_after_the_freeze_fails(frozen: tuple[Path, str, str]) -> None:
    repo, freeze, _ = frozen
    _write(repo, "src/memkernel/core.py", "X = 2\n")
    _commit(repo, "sneaky fix")
    assert check_freeze.check(repo, freeze) == ["not on the allowlist: src/memkernel/core.py"]


def test_a_non_version_change_to_a_version_file_fails(frozen: tuple[Path, str, str]) -> None:
    repo, freeze, _ = frozen
    _write(repo, "pyproject.toml", '[tool.poetry]\nname = "memkernel-x"\nversion = "0.5.0"\n')
    _commit(repo, "rename")
    assert check_freeze.check(repo, freeze) == ["pyproject.toml changed beyond its version line"]


def test_editing_the_preregistration_after_its_commit_fails(frozen: tuple[Path, str, str]) -> None:
    repo, freeze, _ = frozen
    _write(repo, PREREG, "# preregistration, revised after the run\n")
    _commit(repo, "revise")
    assert "the preregistration changed after the preregistration commit" in check_freeze.check(repo, freeze)


def test_moving_prereg_commit_to_a_later_commit_fails(frozen: tuple[Path, str, str]) -> None:
    repo, freeze, _ = frozen
    _write(repo, PREREG, "# preregistration, revised after the run\n")
    later = _commit(repo, "revise")
    _write(repo, PREREG_COMMIT, later + "\n")
    _commit(repo, "point at the revision")
    problems = check_freeze.check(repo, freeze)
    assert "PREREG_COMMIT does not name the first commit after the freeze that touches the preregistration" in problems
    assert f"the preregistration commit must differ from the freeze by exactly {PREREG}" in problems


def test_no_commit_touching_the_preregistration_fails(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _write(repo, "README.md", "x\n")
    freeze = _commit(repo, "freeze")
    _write(repo, PREREG_COMMIT, freeze + "\n")
    _commit(repo, "record without a preregistration")
    problems = check_freeze.check(repo, freeze)
    assert f"no commit after the freeze touches {PREREG}" in problems

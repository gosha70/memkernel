# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""MemKernelSettings loading from the environment and a working-directory .env."""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

import pytest

from memkernel.config import MemKernelSettings

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def cwd(tmp_path: Path) -> Path:
    previous = os.getcwd()
    os.chdir(tmp_path)
    try:
        yield tmp_path
    finally:
        os.chdir(previous)


def test_env_file_with_foreign_keys_is_ignored(
    cwd: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A .env written for other tools must not stop the server from starting (issue #15)."""
    monkeypatch.delenv("MEMKERNEL_PROJECT_ID", raising=False)
    caplog.set_level(logging.WARNING, logger="memkernel.config")
    (cwd / ".env").write_text(
        "COMPOSE_CONVERT_WINDOWS_PATHS=1\nOPENAI_API_KEY=placeholder\nMEMKERNEL_PROJECT_ID=from-env-file\n",
        encoding="utf-8",
    )

    settings = MemKernelSettings()

    assert settings.project_id == "from-env-file"
    assert not hasattr(settings, "compose_convert_windows_paths")
    assert not caplog.records  # foreign keys are not reported


def test_environment_overrides_env_file(cwd: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (cwd / ".env").write_text("MEMKERNEL_PROJECT_ID=from-env-file\n", encoding="utf-8")
    monkeypatch.setenv("MEMKERNEL_PROJECT_ID", "from-environment")

    assert MemKernelSettings().project_id == "from-environment"


def test_misspelled_prefixed_key_in_env_file_is_reported(
    cwd: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """extra="ignore" must not hide a MEMKERNEL_ typo: the server would silently use another project."""
    monkeypatch.delenv("MEMKERNEL_PROJECT_ID", raising=False)
    caplog.set_level(logging.WARNING, logger="memkernel.config")
    (cwd / ".env").write_text("MEMKERNEL_PROJEKT_ID=oops\n", encoding="utf-8")

    settings = MemKernelSettings()

    assert settings.project_id == "default"
    assert [r.levelno for r in caplog.records] == [logging.WARNING]
    assert "MEMKERNEL_PROJEKT_ID" in caplog.text
    assert ".env" in caplog.text


def test_misspelled_prefixed_key_in_environment_is_reported(
    cwd: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.WARNING, logger="memkernel.config")
    monkeypatch.setenv("MEMKERNEL_PROJEKT_ID", "oops")

    MemKernelSettings()

    assert "MEMKERNEL_PROJEKT_ID" in caplog.text
    assert "the environment" in caplog.text

# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""MemKernelSettings loading from the environment and a working-directory .env."""

from __future__ import annotations

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


def test_env_file_with_foreign_keys_is_ignored(cwd: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A .env written for other tools must not stop the server from starting (issue #15)."""
    monkeypatch.delenv("MEMKERNEL_PROJECT_ID", raising=False)
    (cwd / ".env").write_text(
        "COMPOSE_CONVERT_WINDOWS_PATHS=1\nOPENAI_API_KEY=placeholder\nMEMKERNEL_PROJECT_ID=from-env-file\n",
        encoding="utf-8",
    )

    settings = MemKernelSettings()

    assert settings.project_id == "from-env-file"
    assert not hasattr(settings, "compose_convert_windows_paths")


def test_environment_overrides_env_file(cwd: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (cwd / ".env").write_text("MEMKERNEL_PROJECT_ID=from-env-file\n", encoding="utf-8")
    monkeypatch.setenv("MEMKERNEL_PROJECT_ID", "from-environment")

    assert MemKernelSettings().project_id == "from-environment"

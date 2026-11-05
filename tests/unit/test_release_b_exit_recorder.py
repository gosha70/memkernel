# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""The Release B exit recorder's guarantees that need no download (specs/memkernel-0-7-release-b-exit FR-003)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.unit

RECORD = Path(__file__).resolve().parents[2] / "eval" / "release-b-exit" / "record.py"


def _recorder() -> Any:
    spec = importlib.util.spec_from_file_location("release_b_exit_record", RECORD)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_embedding_revision_cannot_be_overridden() -> None:
    record = _recorder()
    with pytest.raises(SystemExit):
        record.main(["--out", "x", "--memkernel", "0.7.0", "--wiki-studio", "0.8.1", "--embedding-revision", "main"])
    assert record.EMBEDDING_REVISION == "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"


def test_another_python_is_refused_before_anything_is_created(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    record = _recorder()
    other = (sys.version_info[0], sys.version_info[1] + 1)
    monkeypatch.setattr(record, "PYTHON", other)
    out = tmp_path / "run"
    with pytest.raises(record.CannotRunError, match="runs under Python"):
        record._record(out, "0.7.0", "0.8.1", False)
    assert not out.exists()


def test_an_interrupted_manifest_write_keeps_the_previous_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = _recorder()
    record._write_manifest(tmp_path, {"outcome": "running", "stage": "download"})

    def full_disk(fd: int) -> None:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(record.os, "fsync", full_disk)
    with pytest.raises(OSError, match="No space left"):
        record._write_manifest(tmp_path, {"outcome": "running", "stage": "install"})

    assert json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8")) == {
        "outcome": "running",
        "stage": "download",
    }

# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""``memkernel session-start`` for other coding tools' hooks (memkernel-0-13-one-store-across-tools FR-003, SC-3)."""

from __future__ import annotations

import io
import json
import re
import uuid
from typing import TYPE_CHECKING, Any

import chromadb
import pytest

from memkernel import session_spool, session_start
from memkernel.config import MemKernelSettings
from memkernel.core.models import MemoryType
from memkernel.factory import build_service
from memkernel.lifecycle import (
    HEADING_SESSION_START,
    STORED_CLOSE,
    STORED_KIND_CHECKPOINT,
    STORED_KIND_CONTEXT,
    STORED_NOTICE,
    STORED_OPEN,
    stored,
)
from memkernel.mcp import server as server_module
from tests.conftest import MockEmbedding

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit


@pytest.fixture
def store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    """A persistent-path store (so a spool exists) with one decision, built the way session-start builds it."""
    monkeypatch.setenv("MEMKERNEL_PROJECT_ID", f"ss-{uuid.uuid4().hex[:8]}")
    monkeypatch.setenv("MEMKERNEL_CHROMA_PERSIST_PATH", str(tmp_path / "chroma"))
    monkeypatch.setenv("MEMKERNEL_STATE_DIR", str(tmp_path / "state"))
    client = chromadb.EphemeralClient()
    built: list[Any] = []

    def build(settings: MemKernelSettings) -> Any:
        service = build_service(settings, embedding=MockEmbedding(), chroma_client=client)
        built.append(service)
        return service

    seed = build(MemKernelSettings())
    seed.retain("Deploys go out on Tuesdays after the release review.", MemoryType.DECISION)
    return build


def _run(
    build: Any, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], args: list[str], stdin: str = ""
) -> str:
    monkeypatch.setattr("sys.stdin", io.StringIO(stdin))
    assert session_start.main(args, build=build) == 0
    return capsys.readouterr().out


def test_plain_prints_the_startup_block(store: Any, monkeypatch: pytest.MonkeyPatch, capsys: Any) -> None:
    out = _run(store, monkeypatch, capsys, ["--format", "plain"], json.dumps({"source": "startup", "session_id": "c1"}))
    assert out.startswith(HEADING_SESSION_START) and "Deploys go out on Tuesdays" in out


def test_cursor_and_antigravity_wrap_the_block_in_their_json(
    store: Any, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    cursor = json.loads(_run(store, monkeypatch, capsys, ["--format", "cursor"], json.dumps({"conversation_id": "x"})))
    assert cursor["additional_context"].startswith(HEADING_SESSION_START)
    antigravity = json.loads(_run(store, monkeypatch, capsys, ["--format", "antigravity"], "{}"))
    (step,) = antigravity["injectSteps"]
    assert step["systemMessage"].startswith(HEADING_SESSION_START)


@pytest.mark.parametrize(("output_format", "expected"), [("plain", ""), ("cursor", "{}\n"), ("antigravity", "{}\n")])
def test_resume_and_fork_print_nothing_to_inject(
    store: Any, monkeypatch: pytest.MonkeyPatch, capsys: Any, output_format: str, expected: str
) -> None:
    for source in ("resume", "fork"):
        payload = json.dumps({"source": source, "session_id": "c1"})
        assert _run(store, monkeypatch, capsys, ["--format", output_format], payload) == expected


@pytest.mark.parametrize("output_format", session_start.FORMATS)
def test_no_source_gets_the_startup_block_and_no_spool_line_is_written(
    store: Any, monkeypatch: pytest.MonkeyPatch, capsys: Any, output_format: str
) -> None:
    out = _run(store, monkeypatch, capsys, ["--format", output_format], "")
    assert HEADING_SESSION_START in out
    path = session_spool.spool_path(MemKernelSettings())
    assert path is not None
    assert not path.exists() or path.read_text(encoding="utf-8") == ""


def test_max_chars_keeps_headings_the_notice_and_whole_elements(
    store: Any, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    seed = store(MemKernelSettings())
    for i in range(40):
        seed.retain(f"Convention {i}: " + "keep every module under four hundred lines. " * 3, MemoryType.CONVENTION)
    full = _run(store, monkeypatch, capsys, ["--format", "plain"], "")
    cut = _run(store, monkeypatch, capsys, ["--format", "plain", "--max-chars", "1500"], "")
    assert len(full) > 1500 >= len(cut.rstrip("\n"))
    headings = [line for line in full.splitlines() if line.startswith("#")]
    assert [line for line in cut.splitlines() if line.startswith("#")] == headings
    if STORED_OPEN in cut:
        assert STORED_NOTICE in cut
    assert cut.count(STORED_OPEN) == cut.count(STORED_CLOSE)
    assert "Cut to 1500 characters" in cut


def test_a_limit_inside_a_memory_drops_that_memory_whole() -> None:
    kept = stored("Deploys go out on Tuesdays.", STORED_KIND_CONTEXT, "ref-a")
    long_body = "\n".join(["First line of the checkpoint. " * 8, "Second line of the checkpoint. " * 8])
    cut_one = stored(long_body, STORED_KIND_CHECKPOINT, "ref-b", block=True)
    text = "\n".join([HEADING_SESSION_START, STORED_NOTICE, kept, cut_one, "- a line after the memories"])
    limit = text.index("Second line")  # inside the multi-line element
    assert text.rfind(STORED_OPEN, 0, limit) > text.rfind(STORED_CLOSE, 0, limit)

    out = session_start.fit(text, limit)

    assert len(out) <= limit
    assert kept in out and "First line of the checkpoint" not in out and 'ref_id="ref-b"' not in out
    tags = re.findall(f"{re.escape(STORED_OPEN)}|{re.escape(STORED_CLOSE)}", out)
    assert tags == [STORED_OPEN, STORED_CLOSE] * (len(tags) // 2) and len(tags) % 2 == 0
    assert STORED_NOTICE in out and out.endswith(session_start.CUT_NOTE.format(limit=limit))


def test_a_failure_prints_nothing_and_still_exits_0(
    monkeypatch: pytest.MonkeyPatch, capsys: Any, caplog: pytest.LogCaptureFixture
) -> None:
    def broken(_: MemKernelSettings) -> Any:
        raise RuntimeError("store unavailable")

    assert _run(broken, monkeypatch, capsys, ["--format", "cursor"], "{}") == "{}\n"
    assert any("session-start failed" in r.message for r in caplog.records)


def test_the_memkernel_command_dispatches_session_start(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake(argv: list[str]) -> int:
        calls.append(argv)
        return 0

    monkeypatch.setattr(session_start, "main", fake)
    assert server_module.main(["session-start", "--format", "cursor"]) == 0
    assert calls == [["--format", "cursor"]]

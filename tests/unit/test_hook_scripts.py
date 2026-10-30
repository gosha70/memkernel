# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""The hook scripts in templates/hooks/, driven like Claude Code drives them (memkernel-0-6-compaction-hooks SC-7).

Each script's ``main()`` runs with a payload on stdin, shaped as the Claude Code hooks reference documents it
(https://code.claude.com/docs/en/hooks, checked 2026-10-29), against an in-memory service: no model download.
"""

from __future__ import annotations

import importlib.util
import io
import json
import uuid
from pathlib import Path
from typing import Any

import chromadb
import pytest

from memkernel.config import MemKernelSettings
from memkernel.core.models import MemoryType
from memkernel.factory import build_service
from memkernel.lifecycle import HEADING_POST_COMPACT, HEADING_SESSION_START
from tests.conftest import MockEmbedding

pytestmark = pytest.mark.unit

HOOKS = Path(__file__).resolve().parents[2] / "templates" / "hooks"
COMMON = {"session_id": "abc123", "transcript_path": "/tmp/t.jsonl", "cwd": "/tmp/project"}
PRE_COMPACT = {**COMMON, "hook_event_name": "PreCompact", "trigger": "manual", "custom_instructions": None}
POST_COMPACT = {
    **COMMON,
    "hook_event_name": "PostCompact",
    "trigger": "auto",
    "compact_summary": "Summary: the store lock landed; next, the hooks.",
}


class _Terminal(io.StringIO):
    """A stdin that is a terminal: reading it would wait for a person."""

    def isatty(self) -> bool:
        return True

    def read(self, *args: Any) -> str:
        raise AssertionError("a hook must not read stdin from a terminal")


@pytest.fixture
def svc(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Any:
    monkeypatch.setenv("MEMKERNEL_PROJECT_ROOT", str(tmp_path))  # the scripts' setdefault then changes nothing
    monkeypatch.setenv("MEMKERNEL_PROJECT_ID", f"hooks-{uuid.uuid4().hex[:8]}")
    monkeypatch.setenv("MEMKERNEL_CHROMA_PERSIST_PATH", "")
    return build_service(MemKernelSettings(), embedding=MockEmbedding(), chroma_client=chromadb.EphemeralClient())


def _run(monkeypatch: pytest.MonkeyPatch, svc: Any, script: str, stdin: Any) -> None:
    spec = importlib.util.spec_from_file_location(f"hook_{script.replace('-', '_')}", HOOKS / f"{script}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "build_service", lambda *args, **kwargs: svc)
    monkeypatch.setattr("sys.stdin", stdin if not isinstance(stdin, dict) else io.StringIO(json.dumps(stdin)))
    module.main()


def test_pre_compact_with_the_reference_payload_retains_nothing(
    monkeypatch: pytest.MonkeyPatch, svc: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    """SC-1: no placeholder checkpoint; the agent's own checkpoint stays the latest."""
    svc.retain("SESSION CHECKPOINT agent\n\nNext: wire the store", MemoryType.EPISODE, checkpoint=True)
    _run(monkeypatch, svc, "pre-compact", PRE_COMPACT)

    out = capsys.readouterr()
    assert out.out == "" and "nothing retained" in out.err
    (checkpoint,) = svc.recall("checkpoint", checkpoint_only=True, touch=False)
    assert "Next: wire the store" in checkpoint.preview


def test_post_compact_retains_compact_summary_and_prints_nothing_to_stdout(
    monkeypatch: pytest.MonkeyPatch, svc: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    """SC-2: the summary is a tagged checkpoint; stdout stays empty (PostCompact output never reaches the model)."""
    _run(monkeypatch, svc, "post-compact", POST_COMPACT)

    out = capsys.readouterr()
    assert out.out == "" and "compaction summary (auto) retained" in out.err
    ref_id = out.err.split("ref_id=")[1].strip()
    memory = svc.get(ref_id, touch=False)
    assert memory is not None and memory.tags == ["checkpoint", "compact-summary", "session:abc123"]
    assert memory.content.endswith("Summary: the store lock landed; next, the hooks.")


@pytest.mark.parametrize(
    ("source", "first_line"),
    [("startup", HEADING_SESSION_START), ("clear", HEADING_SESSION_START), ("compact", HEADING_POST_COMPACT)],
)
def test_session_start_prints_the_block_for_its_source(
    monkeypatch: pytest.MonkeyPatch, svc: Any, capsys: pytest.CaptureFixture[str], source: str, first_line: str
) -> None:
    _run(monkeypatch, svc, "session-start", {**COMMON, "hook_event_name": "SessionStart", "source": source})

    assert capsys.readouterr().out.splitlines()[0] == first_line


@pytest.mark.parametrize("source", ["resume", "fork"])
def test_session_start_prints_nothing_on_resume_and_fork(
    monkeypatch: pytest.MonkeyPatch, svc: Any, capsys: pytest.CaptureFixture[str], source: str
) -> None:
    """SC-3."""
    _run(monkeypatch, svc, "session-start", {**COMMON, "hook_event_name": "SessionStart", "source": source})

    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("stdin", [io.StringIO(""), io.StringIO("not json"), io.StringIO("[1, 2]"), _Terminal()])
def test_session_start_without_a_usable_payload_prints_the_full_block(
    monkeypatch: pytest.MonkeyPatch, svc: Any, capsys: pytest.CaptureFixture[str], stdin: Any
) -> None:
    """SC-5: an empty, invalid or non-object stdin, or a terminal (never read), means no source."""
    _run(monkeypatch, svc, "session-start", stdin)

    assert capsys.readouterr().out.splitlines()[0] == HEADING_SESSION_START


def test_post_compact_from_a_terminal_reads_nothing_and_retains_nothing(
    monkeypatch: pytest.MonkeyPatch, svc: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    _run(monkeypatch, svc, "post-compact", _Terminal())

    assert "nothing retained" in capsys.readouterr().err
    assert svc.recall("checkpoint", checkpoint_only=True, touch=False) == []

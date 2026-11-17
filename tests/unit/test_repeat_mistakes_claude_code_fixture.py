# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""SC-8 on a transcript folder in Claude Code's on-disk shape (memkernel-0-12-capture-core, contributed by DIADE).

``tests/fixtures/transcripts/sc8-claude-code`` holds hand-built lines with the fields and line types Claude Code
2.1.x writes: batched results, ``attachment``, ``system``, ``api-request`` and ``api-request-blob`` lines (the blob
repeats a call's ``tool_use`` and ``tool_result`` parts without a timestamp), a hook-blocked call with
``toolDenialKind``, a piped run, subagent and workflow-agent files, and a ``journal.jsonl``. ``expected.json`` names
each repeat's outcome and why.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from memkernel import recall_log
from memkernel.config import MemKernelSettings
from memkernel.core.models import MemoryType
from memkernel.factory import build_service
from memkernel.transcripts.claude_code import ClaudeCodeTranscriptReader, transcript_files
from tests.conftest import MockEmbedding

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]
COUNT = ROOT / "eval" / "repeat-mistakes" / "count.py"
FIXTURE = ROOT / "tests" / "fixtures" / "transcripts" / "sc8-claude-code"
EXPECTED: dict[str, Any] = json.loads((FIXTURE / "expected.json").read_text(encoding="utf-8"))


def _load() -> Any:
    spec = importlib.util.spec_from_file_location("repeat_mistakes_count_fixture", COUNT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


count_module = _load()


def _time(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def _moved_copy(target: Path, shift: timedelta) -> Path:
    """The fixture folder under ``target``, every line's ``timestamp`` moved by ``shift`` (lines without one kept)."""
    folder = target / "transcripts"
    shutil.copytree(FIXTURE, folder, ignore=shutil.ignore_patterns("expected.json"))
    for path in folder.rglob("*.jsonl"):
        lines = []
        for line in path.read_text(encoding="utf-8").splitlines():
            entry = json.loads(line)
            if "timestamp" in entry:
                moved = _time(entry["timestamp"]) + shift
                entry["timestamp"] = moved.isoformat(timespec="milliseconds").replace("+00:00", "Z")
            lines.append(json.dumps(entry))
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return folder


def test_the_fixture_has_the_noise_it_claims() -> None:
    """The fixture keeps its point: blob lines repeat tool parts without a timestamp, one entry batches results."""
    types: set[str] = set()
    blob_parts = batched = 0
    for path in FIXTURE.rglob("*.jsonl"):
        for line in path.read_text(encoding="utf-8").splitlines():
            entry = json.loads(line)
            types.add(str(entry.get("type")))
            content = (entry.get("message") or {}).get("content")
            parts = [p for p in content if isinstance(p, dict)] if isinstance(content, list) else []
            if entry.get("type") == "api-request-blob":
                assert "timestamp" not in entry
                blob_parts += sum(p.get("type") in {"tool_use", "tool_result"} for p in parts)
            if entry.get("type") == "user" and sum(p.get("type") == "tool_result" for p in parts) > 1:
                batched += 1
    assert {"attachment", "system", "api-request", "api-request-blob", "queue-operation", "last-prompt"} <= types
    assert blob_parts >= 4 and batched >= 1


def test_the_reader_takes_each_call_once_and_skips_the_journal() -> None:
    reader = ClaudeCodeTranscriptReader()
    files = list(transcript_files(FIXTURE))
    assert not [p for p in files if p.name == "journal.jsonl"]
    ids: list[str] = []
    for path in files:
        for session in reader.read(path, include_sidechains=True):
            ids.extend(step.tool_use_id for step in session.steps)
    assert len(ids) == len(set(ids))  # the blob copies are not second steps


def test_sc8_outcomes_on_the_claude_code_shaped_folder(tmp_path: Path) -> None:
    settings = MemKernelSettings(
        project_id="a",
        chroma_persist_path=str(tmp_path / "chroma-a"),
        state_dir=str(tmp_path / "state"),
        recall_log=True,
    )
    svc = build_service(settings, embedding=MockEmbedding(dimension=384))
    refs = {name: svc.retain(text, MemoryType.FACT) for name, text in EXPECTED["memories"].items()}
    del svc
    shift = (datetime.now(UTC) + timedelta(hours=1)) - _time(EXPECTED["base"])
    folder = _moved_copy(tmp_path, shift)
    for recall in EXPECTED["recalls"]:
        ids = [refs[name] for name in recall["memories"]]
        when = _time(recall["at"]) + shift
        if recall["origin"] == "hook":
            recall_log.append(settings, "hook", ids, session_id=recall["session"], block="session-start", now=when)
        else:
            recall_log.append(settings, "tool", ids, query=recall["query"], now=when)

    out = tmp_path / "report.json"
    store = f"name=a,chroma={tmp_path / 'chroma-a'},state={tmp_path / 'state'},project=a"
    assert count_module.main(["--store", store, "--transcripts", str(folder), "--json", str(out)]) == 0
    report = json.loads(out.read_text(encoding="utf-8"))

    found = {(d["session_id"], d["agent_id"]): d for d in report["details"]}
    expected = {(r["session"], r["agent"]): r for r in EXPECTED["repeats"]}
    assert set(found) == set(expected)
    for key, want in expected.items():
        assert (found[key]["outcome"], found[key]["command"]) == (want["outcome"], want["command"]), want["why"]
        assert found[key]["ref_id"] == refs["left_pad"]
    assert not {session for session, _ in found} & set(EXPECTED["no_repeat"])
    assert report["stored_errors"] == EXPECTED["stored_errors"]
    assert report["repeats"] == EXPECTED["repeats_main"]
    assert report["subagent_repeats"] == EXPECTED["subagent_repeats"]

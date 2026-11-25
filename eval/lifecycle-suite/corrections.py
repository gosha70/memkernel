# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""How a correction reaches the next session, per arm (specs/memkernel-0-16-lifecycle-corrections FR-002).

An lc-correct task's ``correction`` is delivered once, to the session after ``after_session``, after the runner has
built that session's starting state (the exposure artifact already copied, so the copy never carries the
correction) and before the agent starts. Each arm gets the correction only through its own workflow:

| Arm | Path |
|---|---|
| ``bare``, ``placebo``, ``protocol``, ``wiki_studio`` | nothing |
| ``claude_md`` | a curator appends the brief to ``CLAUDE.md`` in the carried workspace (decision B1) |
| ``fs_grep`` | a curator writes the brief as a note into the grep directory |
| ``memkernel`` | a superseding retain, or withdraw then retain, per the chain's kind (decision B4) |
| ``memkernel_governed`` | the scripted curator through the gate, then memkernel's governed import (decision B2) |
| ``memkernel_governed_oracle`` | the oracle curator through the gate, then the governed import |
| ``informed`` | nothing here: the brief is in its instruction for the sessions after the correction (decision B3) |
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import curator

if TYPE_CHECKING:
    from pathlib import Path

NONE, CLAUDE_MD, GREP_NOTE, MEMKERNEL, SCRIPTED, ORACLE, BRIEF = (
    "none",
    "claude_md",
    "grep_note",
    "memkernel",
    "curator_scripted",
    "curator_oracle",
    "instruction_brief",
)
PATHS = {
    "bare": NONE,
    "placebo": NONE,
    "protocol": NONE,
    "wiki_studio": NONE,
    "claude_md": CLAUDE_MD,
    "fs_grep": GREP_NOTE,
    "memkernel": MEMKERNEL,
    "memkernel_governed": SCRIPTED,
    "memkernel_governed_oracle": ORACLE,
    "informed": BRIEF,
}
CLAUDE_MD_FILE = "CLAUDE.md"
GREP_NOTE_FILE = "curator-correction.md"


class CorrectionError(RuntimeError):
    """The harness could not deliver the correction (a crashed helper, unreadable output): the trial is invalid."""


def brief_text(correction: dict[str, Any]) -> str:
    """The correction as a curator writes it, for the paths that carry text (CLAUDE.md, the grep note, the brief)."""
    return f"Correction from the team that owns this rule: {correction['headline']}.\n\n{correction['rule']}\n"


def deliver(
    arm: str,
    correction: dict[str, Any],
    workspace: Path,
    memory_dir: Path | None,
    ops: curator.Ops | None,
    cli: curator.Cli | None,
) -> dict[str, Any]:
    """Deliver ``correction`` along ``arm``'s path and return what was done, for the session's receipt.

    Any helper answer the delivery cannot read (malformed JSON, a missing key, an unreadable page) is a harness
    failure, raised as :class:`CorrectionError` so the session is invalid (``correction_failed``), never a crash.
    """
    try:
        return _deliver(arm, correction, workspace, memory_dir, ops, cli)
    except (curator.CuratorError, KeyError, TypeError, ValueError) as exc:
        raise CorrectionError(f"{arm}: the correction's helpers answered unreadably: {exc}") from exc


def _deliver(
    arm: str,
    correction: dict[str, Any],
    workspace: Path,
    memory_dir: Path | None,
    ops: curator.Ops | None,
    cli: curator.Cli | None,
) -> dict[str, Any]:
    path = PATHS[arm]
    if path in (NONE, BRIEF):
        return {"path": path, "delivered": path == BRIEF}
    if path == CLAUDE_MD:
        target = workspace / CLAUDE_MD_FILE
        before = target.read_text(encoding="utf-8") if target.is_file() else ""
        separator = "\n" if before and not before.endswith("\n\n") else ""
        target.write_text(before + separator + "## Correction\n\n" + brief_text(correction), encoding="utf-8")
        return {"path": path, "delivered": True}
    if path == GREP_NOTE:
        if memory_dir is None:
            raise CorrectionError("fs_grep has no grep directory to write the curator's note into")
        (memory_dir / GREP_NOTE_FILE).write_text(brief_text(correction), encoding="utf-8")
        return {"path": path, "delivered": True}
    if ops is None:
        raise CorrectionError(f"{arm}: the memkernel helper is not available")
    if path == MEMKERNEL:
        result = ops("correct", "--brief", _brief_json(correction))
        return {"path": path, "delivered": True, "matched": result["matched"], "new_ref": result["new_ref"]}
    if cli is None:
        raise CorrectionError(f"{arm}: the wiki-studio command line is not available")
    mode = curator.SCRIPTED if path == SCRIPTED else curator.ORACLE
    curated = curator.curate(mode, correction, workspace, ops, cli)
    imported = ops("import")
    if imported.get("import_error"):
        raise CorrectionError(f"governed import failed: {imported['import_error']}")
    return {"path": path, **curated, "imported": imported}


def _brief_json(correction: dict[str, Any]) -> str:
    keys = ("kind", "headline", "rule", "obsolete_patterns")
    return json.dumps({key: correction[key] for key in keys})

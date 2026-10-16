# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""Count-based diagnostics over a chain's session streams (FR-018). Never endpoints."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from records import MEMKERNEL_TOOL_PREFIX

if TYPE_CHECKING:
    from records import StreamSummary

READ_TOOL = "Read"


def _ratio(numerator: int, denominator: int) -> dict[str, int]:
    return {"numerator": numerator, "denominator": denominator}


def _relative(path: str, workspace: Path) -> str:
    candidate = Path(path)
    try:
        return candidate.resolve().relative_to(workspace.resolve()).as_posix()
    except (ValueError, OSError):
        return candidate.as_posix()


def read_paths(summary: StreamSummary, workspace: Path) -> list[str]:
    return [
        _relative(str(use.input.get("file_path", "")), workspace)
        for use in summary.tool_uses
        if use.name == READ_TOOL and use.input.get("file_path")
    ]


def _ref_ids(text: str) -> list[str]:
    try:
        parsed: Any = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return []
    items = parsed if isinstance(parsed, list) else [parsed]
    return [str(item["ref_id"]) for item in items if isinstance(item, dict) and item.get("ref_id")]


def session_diagnostics(
    summary: StreamSummary, workspace: Path, earlier_reads: set[str], hooks: list[dict[str, Any]]
) -> dict[str, dict[str, int]]:
    """Numerator/denominator pairs for one session given the paths earlier sessions of its chain read."""
    reads = read_paths(summary, workspace)
    re_reads = sum(1 for path in reads if path in earlier_reads)

    total_calls = len(summary.tool_uses)
    first_retain = next(
        (i for i, use in enumerate(summary.tool_uses) if use.name == f"{MEMKERNEL_TOOL_PREFIX}retain"), total_calls
    )

    returned: list[str] = []
    used: set[str] = set()
    for use in summary.tool_uses:
        if use.name == f"{MEMKERNEL_TOOL_PREFIX}recall":
            returned += _ref_ids(summary.tool_results.get(use.tool_id, ""))
        elif use.name in (f"{MEMKERNEL_TOOL_PREFIX}get", f"{MEMKERNEL_TOOL_PREFIX}ask") and use.input.get("ref_id"):
            used.add(str(use.input["ref_id"]))
    unique_returned = list(dict.fromkeys(returned))

    return {
        "re_reads_after_resume": _ratio(re_reads, len(reads)),
        "calls_before_first_retain": _ratio(first_retain, total_calls),
        "recall_to_use": _ratio(sum(1 for ref in unique_returned if ref in used), len(unique_returned)),
        "hooks_succeeded": _ratio(sum(1 for h in hooks if h["exit_status"] == 0), len(hooks)),
    }

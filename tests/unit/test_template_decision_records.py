# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""The minimal setup block carries the decision-record form itself (#57, PR #118 review).

The minimal block is pasted into a project's ``CLAUDE.md`` on its own, so it must not send the agent to a section
that lives only in the full instructions, and its record must have the same fields as the full section's.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

INSTRUCTIONS = Path(__file__).resolve().parents[2] / "templates" / "claude-memory-instructions.md"
_FIELD = re.compile(r"^\s*([a-z-]+): ", re.MULTILINE)


def _after(text: str, marker: str) -> str:
    assert marker in text, f"the template no longer contains {marker!r}"
    return text.split(marker, 1)[1]


def _minimal_block() -> str:
    block = _after(_after(INSTRUCTIONS.read_text(encoding="utf-8"), "## Minimal setup"), "```markdown\n")
    assert "\n```\n" in block, "the minimal block's fence is not closed"
    return block.split("\n```\n", 1)[0]


def _full_record_fields() -> list[str]:
    record = _after(_after(INSTRUCTIONS.read_text(encoding="utf-8"), "### Decision records"), "```\n")
    return _FIELD.findall(record.split("```", 1)[0])


def test_the_minimal_block_points_to_no_section_outside_it() -> None:
    block = _minimal_block()
    headings = {line.lstrip("#").strip() for line in block.splitlines() if line.startswith("#")}
    missing = [name for name in re.findall(r'see "([^"]+)"', block) if name not in headings]
    assert missing == [], f"the minimal block refers to sections it does not contain: {missing}"


def test_the_minimal_block_has_the_full_decision_record_fields() -> None:
    fields = _full_record_fields()
    assert fields[0] == "decision" and "revisit-when" in fields, fields
    block = _minimal_block()
    assert [f for f in _FIELD.findall(block) if f in fields] == fields

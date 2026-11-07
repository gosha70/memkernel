# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""The agent templates' wiki workflow lines agree with governed import (#86).

With wiki-studio 0.7 or later, ``wiki_import`` imports only approved pages, so every place the templates tell an
agent to run ``wiki_import`` must also name the approval step, and the one-line workflow must read the same in
every template that carries it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

TEMPLATES = Path(__file__).resolve().parents[2] / "templates"
INSTRUCTIONS = TEMPLATES / "claude-memory-instructions.md"
KIRO_STEERING = TEMPLATES / "kiro" / "steering" / "memory.md"
APPROVAL = "wiki-studio approve"


def _paragraphs(path: Path) -> list[str]:
    """Blank-line separated blocks; a heading starts a new block."""
    blocks: list[str] = []
    current: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            if current:
                blocks.append("\n".join(current))
            current = [line] if line.startswith("#") else []
            continue
        current.append(line)
    if current:
        blocks.append("\n".join(current))
    return blocks


def _workflow_lines(path: Path) -> list[str]:
    """The one-line wiki workflows: ``wiki_export()`` → … → ``wiki_import()``."""
    return [
        " ".join(line.split())
        for line in path.read_text(encoding="utf-8").splitlines()
        if "wiki_export()" in line and "→" in line and "wiki_import()" in line
    ]


@pytest.mark.parametrize("path", [INSTRUCTIONS, KIRO_STEERING], ids=lambda p: p.relative_to(TEMPLATES).as_posix())
def test_every_mention_of_wiki_import_names_the_approval_step(path: Path) -> None:
    mentions = [block for block in _paragraphs(path) if re.search(r"\bwiki_import\b", block)]
    assert mentions, f"{path.name} no longer mentions wiki_import"
    missing = [block for block in mentions if APPROVAL not in block]
    assert missing == [], f"{path.name}: wiki_import without the approval step:\n" + "\n---\n".join(missing)


def test_the_one_line_workflow_reads_the_same_in_every_template() -> None:
    lines = {path.name: _workflow_lines(path) for path in (INSTRUCTIONS, KIRO_STEERING)}
    assert all(len(found) == 1 for found in lines.values()), lines
    assert len({found[0] for found in lines.values()}) == 1, lines
    assert APPROVAL in next(iter(lines.values()))[0]

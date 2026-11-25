# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""The three-outcome checker of the lc-correct group (specs/memkernel-0-16-lifecycle-corrections FR-001).

The evaluation session writes its answer to ``ANSWER.md``. The hidden references in ``<oracle>/answers.json`` hold
two lists of case-insensitive regular expressions: ``informed`` (the corrected rule, Y) and ``obsolete`` (the rule
before the correction, X). An answer that matches an informed pattern is ``informed`` and passes, even when it also
names X ("it was X; now it's Y"); one that matches only an obsolete pattern is ``obsolete``; anything else, a missing
answer included, is ``other``. The stated limit (FR-001): an answer naming both values without saying which holds
also passes.

No candidate code runs: the answer is read as text, so no oracle driver is needed.
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

ANSWER_FILE = "ANSWER.md"
ANSWERS_FILE = "answers.json"
INFORMED, OBSOLETE, OTHER = "informed", "obsolete", "other"
ANSWER_CLASSES = (INFORMED, OBSOLETE, OTHER)
MAX_ANSWER_BYTES = 64_000  # an answer is a sentence or two; a larger file is read up to this size


def _patterns(oracle_dir: Path) -> tuple[list[re.Pattern[str]], list[re.Pattern[str]]]:
    raw = json.loads((oracle_dir / ANSWERS_FILE).read_text(encoding="utf-8"))
    informed = [re.compile(str(p), re.IGNORECASE) for p in raw[INFORMED]]
    obsolete = [re.compile(str(p), re.IGNORECASE) for p in raw[OBSOLETE]]
    return informed, obsolete


def answer_text(workdir: Path) -> str | None:
    """The answer, or None when there is no regular file (a symlink is never followed out of the workspace)."""
    path = workdir / ANSWER_FILE
    if path.is_symlink() or not path.is_file():
        return None
    with path.open("rb") as handle:
        return handle.read(MAX_ANSWER_BYTES).decode("utf-8", errors="replace")


def classify_text(text: str | None, informed: list[re.Pattern[str]], obsolete: list[re.Pattern[str]]) -> str:
    if text is None:
        return OTHER
    if any(p.search(text) for p in informed):
        return INFORMED
    if any(p.search(text) for p in obsolete):
        return OBSOLETE
    return OTHER


def classify(workdir: Path, oracle_dir: Path) -> str:
    informed, obsolete = _patterns(oracle_dir)
    return classify_text(answer_text(workdir), informed, obsolete)


def check(workdir: Path, oracle_dir: Path) -> tuple[bool, str]:
    outcome = classify(workdir, oracle_dir)
    return outcome == INFORMED, outcome

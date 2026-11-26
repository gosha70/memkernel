# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""The corrected line with the obsolete one appended: the wrong number of parts, other."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

ANSWER = "Answer: 0; 10 minutes"
EXPECTED = "other"  # the checker's class for this answer


def apply(workdir: Path) -> None:
    (workdir / "ANSWER.md").write_text(ANSWER + "\n", encoding="utf-8")

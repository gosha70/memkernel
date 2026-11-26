# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""The obsolete rule on the answer line, the corrected one in prose: obsolete (A1)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

ANSWER = "Answer: 11 weeks\n\nIn about two weeks: production access is reviewed monthly."
EXPECTED = "obsolete"  # the checker's class for this answer


def apply(workdir: Path) -> None:
    (workdir / "ANSWER.md").write_text(ANSWER + "\n", encoding="utf-8")

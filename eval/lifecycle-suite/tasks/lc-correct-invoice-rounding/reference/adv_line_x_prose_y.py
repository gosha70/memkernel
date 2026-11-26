# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""The obsolete rule on the answer line, the corrected one in prose: obsolete (A1)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

ANSWER = "Answer: 2.35\n\n2.34, because amounts are rounded half to even (banker's rounding)."
EXPECTED = "obsolete"  # the checker's class for this answer


def apply(workdir: Path) -> None:
    (workdir / "ANSWER.md").write_text(ANSWER + "\n", encoding="utf-8")

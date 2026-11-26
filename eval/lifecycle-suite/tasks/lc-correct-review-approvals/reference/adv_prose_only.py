# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""The corrected rule in prose, with no answer line: other (A1)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

ANSWER = "No: changes under payments/ need two approvals, one of them from a code owner."
EXPECTED = "other"  # the checker's class for this answer


def apply(workdir: Path) -> None:
    (workdir / "ANSWER.md").write_text(ANSWER + "\n", encoding="utf-8")

# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""Names both rules and says which holds now: passes (FR-001, A1)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

ANSWER = "Answer: Monday; 09:00 UTC\n\nThe old rule allowed Friday after 17:00 UTC, but now the earliest is Monday at 09:00 UTC."
EXPECTED = "informed"  # the checker's class for this answer


def apply(workdir: Path) -> None:
    (workdir / "ANSWER.md").write_text(ANSWER + "\n", encoding="utf-8")

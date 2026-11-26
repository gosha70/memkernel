# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""Names both rules and says which holds now: passes (FR-001, A1)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

ANSWER = "Answer: 90\n\nIt used to be 30 days, but backups are now kept for 90 days, so up to 90 days back."
EXPECTED = "informed"  # the checker's class for this answer


def apply(workdir: Path) -> None:
    (workdir / "ANSWER.md").write_text(ANSWER + "\n", encoding="utf-8")

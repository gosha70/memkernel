# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""Names both rules and says which holds now: passes (FR-001, A1)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

ANSWER = "Answer: 0\n\nThe old policy said to retry three times immediately, but a non-idempotent payment call must not be retried now."
EXPECTED = "informed"  # the checker's class for this answer


def apply(workdir: Path) -> None:
    (workdir / "ANSWER.md").write_text(ANSWER + "\n", encoding="utf-8")

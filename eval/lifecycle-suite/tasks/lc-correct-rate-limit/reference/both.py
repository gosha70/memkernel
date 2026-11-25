# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""Names both rules and says which holds now: passes (FR-001)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

ANSWER = "Under the old 600-per-minute tenant limit all would pass, but now only 120 per minute per key are accepted."


def apply(workdir: Path) -> None:
    (workdir / "ANSWER.md").write_text(ANSWER + "\n", encoding="utf-8")

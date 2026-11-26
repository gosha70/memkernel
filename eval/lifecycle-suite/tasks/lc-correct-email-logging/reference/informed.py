# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""The corrected rule."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

ANSWER = "Answer: no; internal user id\n\nOnly the internal user id; never the email address, hashed or not."
EXPECTED = "informed"  # the checker's class for this answer


def apply(workdir: Path) -> None:
    (workdir / "ANSWER.md").write_text(ANSWER + "\n", encoding="utf-8")

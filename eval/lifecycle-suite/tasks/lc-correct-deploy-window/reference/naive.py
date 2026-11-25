# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""The obsolete rule, as recorded before the correction."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

ANSWER = "It can go out on Friday after 17:00 UTC."


def apply(workdir: Path) -> None:
    (workdir / "ANSWER.md").write_text(ANSWER + "\n", encoding="utf-8")

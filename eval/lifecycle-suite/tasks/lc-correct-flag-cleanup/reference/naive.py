# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""The obsolete rule, as recorded before the correction."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

ANSWER = "Nothing yet: it can stay in the code until a year after rollout."


def apply(workdir: Path) -> None:
    (workdir / "ANSWER.md").write_text(ANSWER + "\n", encoding="utf-8")

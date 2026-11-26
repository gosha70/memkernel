# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""Classify ANSWER.md against the hidden references: informed passes, obsolete and other fail."""

from __future__ import annotations

from typing import TYPE_CHECKING

import correct_checker

if TYPE_CHECKING:
    from pathlib import Path


def check(workdir: Path, oracle_dir: Path) -> tuple[bool, str]:
    return correct_checker.check(workdir, oracle_dir)


def classify(workdir: Path, oracle_dir: Path) -> str:
    return correct_checker.classify(workdir, oracle_dir)


def other_reason(workdir: Path, oracle_dir: Path) -> str | None:
    return correct_checker.other_reason(workdir, oracle_dir)

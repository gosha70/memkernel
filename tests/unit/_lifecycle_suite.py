# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""Import helper for the stdlib lifecycle suite under eval/lifecycle-suite (not a package: hyphenated dir)."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[2]
SUITE_DIR = REPO_ROOT / "eval" / "lifecycle-suite"
if str(SUITE_DIR) not in sys.path:
    sys.path.insert(0, str(SUITE_DIR))


def load(name: str) -> ModuleType:
    return importlib.import_module(name)

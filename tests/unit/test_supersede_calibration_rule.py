# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""D3's rule for the supersede-suggestion threshold, on synthetic similarities (no model)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.unit

CALIBRATE = Path(__file__).resolve().parents[2] / "eval" / "supersede-threshold" / "calibrate.py"


def _load() -> Any:
    spec = importlib.util.spec_from_file_location("supersede_calibrate_rule", CALIBRATE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


calibrate = _load()


def _pairs(versions: list[float], different: list[float]) -> list[tuple[str, float]]:
    return [("version", s) for s in versions] + [("different", s) for s in different]


def test_the_highest_threshold_catching_as_many_versions_as_the_lowest_qualifying_one() -> None:
    """The lowest qualifying threshold is 0.59 (one different pair at 0.604); every version is at 0.614 or above, so
    0.61 catches as many and suggests none: the rule picks 0.61, not 0.59 and not 0.62."""
    result = calibrate.choose(_pairs([0.614] + [0.9] * 29, [0.604, 0.58, 0.55] + [0.3] * 27), "m")
    assert result.passes and result.threshold == 0.61
    assert (result.versions_caught, result.different_suggested) == (30, 0)


def test_the_stop_below_24_of_30() -> None:
    """Two different pairs at 0.85 and 0.9 push the lowest qualifying threshold to 0.86, where only 23 versions (those
    at 0.95) are caught: no default, the numbers go to the owner."""
    result = calibrate.choose(_pairs([0.95] * 23 + [0.6] * 7, [0.9, 0.85] + [0.3] * 28), "m")
    assert not result.passes and result.threshold is None and result.versions_caught == 23


def test_no_qualifying_threshold() -> None:
    result = calibrate.choose(_pairs([0.995] * 30, [0.995] * 30), "m")
    assert not result.passes and result.threshold is None


def test_the_table_covers_every_threshold_the_rule_considers() -> None:
    rows = calibrate.table(_pairs([0.7], [0.4]))
    assert [r[0] for r in rows][:2] == [0.5, 0.51] and rows[-1][0] == 0.99 and len(rows) == 50

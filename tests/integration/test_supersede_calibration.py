# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""The shipped supersede-suggestion threshold is the one D3's rule picks for the default model
(memkernel-0-17-supersede-and-canonical-hash D3, SC-2). Slow: it loads the embedding model."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

from memkernel.config import MemKernelSettings

pytestmark = [pytest.mark.integration, pytest.mark.slow]

CALIBRATE = Path(__file__).resolve().parents[2] / "eval" / "supersede-threshold" / "calibrate.py"


def _calibrate() -> Any:
    spec = importlib.util.spec_from_file_location("supersede_calibrate", CALIBRATE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_the_default_threshold_is_the_one_the_rule_picks_for_the_default_model() -> None:
    from memkernel.retrieval.embeddings import SentenceTransformerEmbedding

    calibrate = _calibrate()
    settings = MemKernelSettings()
    pairs = json.loads(calibrate.PAIRS.read_text(encoding="utf-8"))["pairs"]
    assert len(pairs) == 60 and sum(p["kind"] == "version" for p in pairs) == 30
    rows = calibrate.similarities(pairs, SentenceTransformerEmbedding(settings).embed)
    result = calibrate.choose([(kind, s) for kind, _, s in rows], settings.embedding_model)
    assert result.passes and result.versions_caught >= calibrate.MIN_VERSIONS
    assert result.threshold == settings.supersede_suggest_threshold

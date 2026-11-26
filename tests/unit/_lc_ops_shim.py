# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""Run eval/lifecycle-suite/memkernel_ops.py with the test suite's MockEmbedding, so no model is downloaded.

The lifecycle runner calls ``[*ops_command, <subcommand>, ...]``; tests set ``ops_command`` to this script.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "eval" / "lifecycle-suite")]

import memkernel_ops  # noqa: E402

from tests.conftest import MockEmbedding  # noqa: E402

if __name__ == "__main__":
    sys.exit(memkernel_ops.main(sys.argv[1:], embedding=MockEmbedding()))

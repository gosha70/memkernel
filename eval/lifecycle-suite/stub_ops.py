#!/usr/bin/env python3
# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""Scripted stand-in for ``memkernel_ops.py`` used by ``runner.py demo``: no store, no model.

It answers each subcommand with a fixed JSON object, and ``correct`` leaves a marker in the chain's store directory
so the demo can see that the memkernel arm's correction went through the memkernel path.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

CORRECTION_MARKER = "stub-correction-marker"


def main(argv: list[str]) -> int:
    command = argv[0] if argv else ""
    if command == "correct":
        store = os.environ.get("MEMKERNEL_CHROMA_PERSIST_PATH")
        if store:
            Path(store, CORRECTION_MARKER).write_text(json.loads(argv[2])["headline"] + "\n", encoding="utf-8")
        result: dict[str, object] = {"kind": json.loads(argv[2])["kind"], "matched": [], "new_ref": "stub-ref"}
    elif command == "exists":
        result = {"ref_id": argv[1], "live": True}
    elif command == "find":
        result = {"ref_ids": []}
    elif command == "import":
        result = {"governed": True, "imported": [], "corrections": [], "unresolved": [], "import_error": None}
    elif command == "gate":
        result = {"landed": [], "approved": [], "unreviewed_drafts": [], "breaches": [], "lint_violations": 0}
    else:
        print(f"unknown command {command!r}", file=sys.stderr)
        return 2
    result["uid"] = os.geteuid()  # who the helper ran as: the demo checks it is the grader in the image
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

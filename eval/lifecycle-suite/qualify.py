#!/usr/bin/env python3
# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""Qualify the lc-correct chains from their calibration (specs/memkernel-0-16-lifecycle-corrections FR-003).

A chain enters the measured set only if the negative control fails and the informed reference passes: every valid
``bare`` trial answers something other than the corrected rule, every valid ``informed`` trial answers it, and each
arm has at least one valid trial. A chain that fails the rule is reported with the reason, not rewritten after the
fact. Calibration qualifies the set; it is not evidence of a gain.

    qualify.py --receipts receipts.jsonl [--out calibrated.json]

The output, with the receipts' sha256, is what the preregistration freezes before a measured run.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

from records import read_receipts

CORRECT_GROUP = "lc-correct"
CONTROL, INFORMED_ARM = "bare", "informed"
INFORMED = "informed"


def qualify(receipts: list[dict[str, Any]]) -> dict[str, Any]:
    final = [
        r
        for r in receipts
        if r["group"] == CORRECT_GROUP and r["phase"] == "calibration" and r["stage"] == "evaluation"
    ]
    trials: dict[str, dict[str, list[str | None]]] = defaultdict(lambda: {CONTROL: [], INFORMED_ARM: []})
    invalid: dict[str, int] = defaultdict(int)
    for r in final:
        if r["arm"] not in (CONTROL, INFORMED_ARM):
            raise ValueError(f"{r['chain_id']}: arm {r['arm']} has no place in an lc-correct calibration")
        if r["valid"]:
            answer = "timeout" if r["outcome"] == "timeout" else r.get("answer_class")
            trials[r["task_id"]][r["arm"]].append(answer)
        else:
            invalid[r["task_id"]] += 1
            _ = trials[r["task_id"]]  # the chain is listed even when every trial is invalid
    qualified, dropped, table = [], [], []
    for task_id in sorted(trials):
        control, informed = trials[task_id][CONTROL], trials[task_id][INFORMED_ARM]
        if not control or not informed:
            reason = f"no valid {CONTROL if not control else INFORMED_ARM} trial"
        elif any(a == INFORMED for a in control):
            reason = f"{CONTROL} answered the corrected rule in {sum(a == INFORMED for a in control)} of {len(control)}"
        elif any(a != INFORMED for a in informed):
            reason = (
                f"{INFORMED_ARM} missed the corrected rule in {sum(a != INFORMED for a in informed)} of {len(informed)}"
            )
        else:
            reason = ""
        if reason:
            dropped.append({"task_id": task_id, "reason": reason})
        else:
            qualified.append(task_id)
        table.append(
            {
                "task_id": task_id,
                CONTROL: dict(sorted(_count(control).items())),
                INFORMED_ARM: dict(sorted(_count(informed).items())),
                "invalid": invalid[task_id],
                "qualified": not reason,
            }
        )
    return {"qualified": qualified, "dropped": dropped, "chains": table}


def _count(answers: list[str | None]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for answer in answers:
        counts[str(answer)] += 1
    return counts


def _fmt(counts: dict[str, int]) -> str:
    return ", ".join(f"{k} {v}" for k, v in counts.items()) or "none"


def render(result: dict[str, Any]) -> str:
    lines = [
        "| Chain | bare (answers) | informed (answers) | Invalid | Qualified |",
        "|---|---|---|---|---|",
    ]
    for row in result["chains"]:
        lines.append(
            f"| {row['task_id']} | {_fmt(row[CONTROL])} | {_fmt(row[INFORMED_ARM])} | {row['invalid']} "
            f"| {'yes' if row['qualified'] else 'no'} |"
        )
    lines += ["", f"Qualified: {len(result['qualified'])} of {len(result['chains'])} chains."]
    lines += [f"- Dropped {d['task_id']}: {d['reason']}" for d in result["dropped"]]
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--receipts", type=Path, required=True)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    result = qualify(read_receipts(args.receipts))
    result["receipts_sha256"] = hashlib.sha256(args.receipts.read_bytes()).hexdigest()
    print(render(result))
    if args.out is not None:
        args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

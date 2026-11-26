#!/usr/bin/env python3
# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""Qualify the lc-correct chains from their calibration (specs/memkernel-0-16-lifecycle-corrections FR-003).

A chain enters the measured set only if the negative control fails and the informed reference passes: every valid
``bare`` trial answers something other than the corrected rule, every valid ``informed`` trial answers it, and each
arm has at least one valid trial. A chain that fails the rule is reported with the reason, not rewritten after the
fact. Calibration qualifies the set; it is not evidence of a gain.

    qualify.py --receipts receipts.jsonl --runs R_CAL [--tasks-root DIR] [--out calibrated.json]

Only a complete calibration qualifies: every lc-correct task under ``--tasks-root``, with bare and informed, for
``--runs`` runs each, every session recorded once; anything else is refused (exit 2) and nothing is written.

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
ARMS = (CONTROL, INFORMED_ARM)
SUITE_DIR = Path(__file__).resolve().parent
INFORMED = "informed"


def qualify(receipts: list[dict[str, Any]], tasks: list[str], runs: int) -> dict[str, Any]:
    """Qualify ``tasks`` from a complete calibration: exactly ``tasks`` x (bare, informed) x ``runs`` chains.

    Raises ``ValueError`` for anything but that manifest: a receipt from another group or phase, a measured arm, a
    chain that is missing or not expected, a session recorded twice, or a chain whose sessions do not start at 0
    and run without a gap. A chain that stopped at an invalid session
    is complete (its receipts end there) and counts as an invalid trial, never as qualified evidence.
    """
    expected = {f"{task}.{arm}.r{run}": (task, arm) for task in tasks for arm in ARMS for run in range(runs)}
    sessions: dict[str, list[dict[str, Any]]] = defaultdict(list)
    seen: set[tuple[str, int]] = set()
    for r in receipts:
        if r["group"] != CORRECT_GROUP or r["phase"] != "calibration":
            raise ValueError(f"{r['chain_id']}: a {r['phase']} {r['group']} receipt is not lc-correct calibration")
        if r["arm"] not in ARMS:
            raise ValueError(f"{r['chain_id']}: arm {r['arm']} has no place in an lc-correct calibration")
        if r["chain_id"] not in expected:
            raise ValueError(f"{r['chain_id']}: not a chain of this calibration ({len(tasks)} tasks x {runs} runs)")
        key = (r["chain_id"], int(r["position"]))
        if key in seen:
            raise ValueError(f"{r['chain_id']}: session {r['position']} is recorded twice")
        seen.add(key)
        sessions[r["chain_id"]].append(r)
    missing = sorted(set(expected) - set(sessions))
    if missing:
        raise ValueError(f"incomplete calibration: {len(missing)} chain(s) missing, e.g. {', '.join(missing[:3])}")
    trials: dict[str, dict[str, list[str | None]]] = {task: {CONTROL: [], INFORMED_ARM: []} for task in tasks}
    invalid: dict[str, int] = defaultdict(int)
    for chain_id, (task, arm) in sorted(expected.items()):
        ordered = sorted(sessions[chain_id], key=lambda r: int(r["position"]))
        positions = [int(r["position"]) for r in ordered]
        if positions != list(range(len(positions))):  # a chain starts at session 0 and has no gap
            raise ValueError(f"{chain_id}: sessions {positions} do not run 0..{len(positions) - 1} without a gap")
        final = ordered[-1]
        if all(r["valid"] for r in ordered) and final["stage"] == "evaluation":
            trials[task][arm].append("timeout" if final["outcome"] == "timeout" else final.get("answer_class"))
        else:
            invalid[task] += 1
    qualified, dropped, table = [], [], []
    for task_id in tasks:
        control, informed = trials[task_id][CONTROL], trials[task_id][INFORMED_ARM]
        if not control or not informed:
            reason = f"no valid {CONTROL if not control else INFORMED_ARM} trial"
        elif any(a == INFORMED for a in control):
            reason = f"{CONTROL} answered the corrected rule in {sum(a == INFORMED for a in control)} of {len(control)}"
        elif any(a != INFORMED for a in informed):
            misses = sum(a != INFORMED for a in informed)
            reason = f"{INFORMED_ARM} missed the corrected rule in {misses} of {len(informed)}"
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
    return {"qualified": qualified, "dropped": dropped, "chains": table, "tasks": tasks, "runs": runs}


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
    parser.add_argument("--runs", type=int, required=True, help="R_cal: the runs per chain per arm the run made")
    parser.add_argument("--tasks-root", type=Path, default=SUITE_DIR / "tasks")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    tasks = sorted(p.name for p in args.tasks_root.iterdir() if p.name.startswith(f"{CORRECT_GROUP}-"))
    try:
        result = qualify(read_receipts(args.receipts), tasks, args.runs)
    except ValueError as exc:
        print(f"qualify: {exc}", file=sys.stderr)
        return 2
    result["receipts_sha256"] = hashlib.sha256(args.receipts.read_bytes()).hexdigest()
    print(render(result))
    if args.out is not None:
        args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

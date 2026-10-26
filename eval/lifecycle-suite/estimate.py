# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""The measured run's cost estimate and its runner arguments, read from the preregistration (FR-016).

The estimate is computed, never typed in: from the committed calibration receipts (their token classes, plus
``compaction_tokens_estimate`` at the input price), as mean cost per chain per group, scaled to the preregistered
tasks, arms and runs, at the preregistered prices, plus the preregistered allowance for invalid trials.

    estimate.py --preregistration FILE [--limit USD]   print the estimate; with --limit, refuse (exit 1) when the
                                                        estimate plus PREFLIGHT_MARGIN exceeds the limit, or when the
                                                        limit is not the preregistered one
    estimate.py --preregistration FILE --runner-args   print the runner's --task/--arm/--runs/--model arguments

The preregistration carries its parameters in exactly one fenced ``json`` block.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

from records import read_receipts

SUITE_DIR = Path(__file__).resolve().parent
REPO_DIR = SUITE_DIR.parent.parent
PREFLIGHT_MARGIN = 0.30  # FR-016: preflight refuses when the estimate plus 30 percent exceeds the spend limit
GROUPS = ("lc-retain", "lc-reval", "lc-wiki", "lc-compact")
TOKEN_CLASSES = ("input", "cache_write", "cache_read", "output")
PER_TOKEN = 1_000_000  # prices are USD per million tokens
REQUIRED = (
    "model",
    "tasks",
    "arms",
    "runs_per_arm_per_task",
    "prices_usd_per_mtok",
    "prices_as_of",
    "invalid_allowance",
    "calibration_receipts",
    "spend_limit_usd",
)
_JSON_BLOCK = re.compile(r"^```json\n(.*?)^```", re.MULTILINE | re.DOTALL)


def load_parameters(text: str) -> dict[str, Any]:
    blocks = _JSON_BLOCK.findall(text)
    if len(blocks) != 1:
        raise ValueError(f"the preregistration must hold exactly one ```json block of parameters, found {len(blocks)}")
    parameters: dict[str, Any] = json.loads(blocks[0])
    missing = [key for key in REQUIRED if key not in parameters]
    if missing:
        raise ValueError(f"the preregistration's parameters lack: {', '.join(missing)}")
    _check_numbers(parameters)
    return parameters


def _number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)


def _check_numbers(parameters: dict[str, Any]) -> None:
    """A spend check on NaN or a negative price passes anything; refuse such parameters outright."""
    prices = parameters["prices_usd_per_mtok"]
    bad = [] if isinstance(prices, dict) else ["prices_usd_per_mtok"]
    if isinstance(prices, dict):
        bad += [
            f"prices_usd_per_mtok.{cls}" for cls in TOKEN_CLASSES if not (_number(prices.get(cls)) and prices[cls] > 0)
        ]
    runs = parameters["runs_per_arm_per_task"]
    if not (isinstance(runs, int) and not isinstance(runs, bool) and runs > 0):
        bad.append("runs_per_arm_per_task")
    if not (_number(parameters["invalid_allowance"]) and parameters["invalid_allowance"] >= 0):
        bad.append("invalid_allowance")
    if not (_number(parameters["spend_limit_usd"]) and parameters["spend_limit_usd"] > 0):
        bad.append("spend_limit_usd")
    if bad:
        raise ValueError(f"the preregistration's parameters are not finite, positive numbers: {', '.join(bad)}")


def task_group(task_id: str) -> str:
    for group in GROUPS:
        if task_id.startswith(group + "-"):
            return group
    raise ValueError(f"task {task_id} belongs to no lifecycle group")


def arm_groups(arm: str, suite: Path = SUITE_DIR) -> tuple[str, ...]:
    """The groups an arm runs on, from its frozen configuration (empty: every group)."""
    config = json.loads((suite / "arms" / arm / "config.frozen.json").read_text(encoding="utf-8"))
    return tuple(config.get("groups", [])) or GROUPS


def chain_costs(receipts: list[dict[str, Any]], prices: dict[str, float]) -> dict[str, list[float]]:
    """Cost of each calibration chain in USD, by group; the compaction calls' input is priced as input."""
    chains: dict[tuple[str, str], float] = defaultdict(float)
    groups: dict[tuple[str, str], str] = {}
    for r in receipts:
        key = (r["run_id"], r["chain_id"])
        tokens = sum(r["tokens"][cls] * prices[cls] for cls in TOKEN_CLASSES)
        chains[key] += (tokens + r["compaction_tokens_estimate"] * prices["input"]) / PER_TOKEN
        groups[key] = r["group"]
    by_group: dict[str, list[float]] = defaultdict(list)
    for key in sorted(chains):
        by_group[groups[key]].append(chains[key])
    return dict(by_group)


def estimate(parameters: dict[str, Any], receipts: list[dict[str, Any]], suite: Path = SUITE_DIR) -> dict[str, Any]:
    costs = chain_costs(receipts, {k: float(v) for k, v in parameters["prices_usd_per_mtok"].items()})
    runs = int(parameters["runs_per_arm_per_task"])
    chains: dict[str, int] = defaultdict(int)
    for task in parameters["tasks"]:
        group = task_group(task)
        chains[group] += runs * sum(1 for arm in parameters["arms"] if group in arm_groups(arm, suite))
    per_group = {}
    for group in sorted(chains):
        if not costs.get(group):
            raise ValueError(f"the calibration receipts hold no {group} chain to estimate from")
        mean = sum(costs[group]) / len(costs[group])
        per_group[group] = {"chains": chains[group], "mean_chain_usd": mean, "usd": mean * chains[group]}
    subtotal = sum(g["usd"] for g in per_group.values())
    return {
        "per_group": per_group,
        "subtotal_usd": subtotal,
        "total_usd": subtotal * (1 + float(parameters["invalid_allowance"])),
    }


def runner_args(parameters: dict[str, Any]) -> list[str]:
    args = [item for task in parameters["tasks"] for item in ("--task", task)]
    args += [item for arm in parameters["arms"] for item in ("--arm", arm)]
    return [*args, "--runs", str(int(parameters["runs_per_arm_per_task"])), "--model", str(parameters["model"])]


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="The measured run's cost estimate, from the preregistration")
    parser.add_argument("--preregistration", type=Path, required=True)
    parser.add_argument("--repo", type=Path, default=REPO_DIR, help="where calibration_receipts is relative to")
    parser.add_argument("--limit", type=float, help="the workspace's spend limit in USD, as the Console shows it")
    parser.add_argument("--runner-args", action="store_true")
    args = parser.parse_args(argv)
    try:
        parameters = load_parameters(args.preregistration.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"estimate: {exc}", file=sys.stderr)
        return 1
    if args.runner_args:
        print("\n".join(runner_args(parameters)))
        return 0
    receipts = read_receipts(args.repo / parameters["calibration_receipts"])
    result = estimate(parameters, receipts)
    for group, g in result["per_group"].items():
        print(f"estimate: {group}: {g['chains']} chains x ${g['mean_chain_usd']:.4f} = ${g['usd']:.2f}")
    print(
        f"estimate: ${result['total_usd']:.2f} (${result['subtotal_usd']:.2f} plus "
        f"{float(parameters['invalid_allowance']):.0%} for invalid trials; prices of {parameters['prices_as_of']}, "
        f"calibration receipts {parameters['calibration_receipts']})"
    )
    if args.limit is None:
        return 0
    if not (math.isfinite(args.limit) and args.limit > 0 and math.isfinite(result["total_usd"])):
        print("estimate: the limit and the estimate must be finite, positive amounts; refusing", file=sys.stderr)
        return 1
    preregistered = float(parameters["spend_limit_usd"])
    if args.limit != preregistered:
        print(
            f"estimate: the limit entered, ${args.limit:.2f}, is not the preregistered ${preregistered:.2f}; refusing",
            file=sys.stderr,
        )
        return 1
    needed = result["total_usd"] * (1 + PREFLIGHT_MARGIN)
    if needed > args.limit:
        print(
            f"estimate: the estimate plus {PREFLIGHT_MARGIN:.0%}, ${needed:.2f}, exceeds the spend limit "
            f"${args.limit:.2f}; refusing",
            file=sys.stderr,
        )
        return 1
    print(f"estimate: plus {PREFLIGHT_MARGIN:.0%}, ${needed:.2f}, is within the spend limit ${args.limit:.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

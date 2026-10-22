#!/usr/bin/env python3
# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""Derive the lifecycle report from committed receipts alone (FR-015a, FR-017, FR-018).

    report.py --receipts results/<run>/receipts.jsonl [--receipts ...] --params report-params.json > report.md

Trial = one chain (task, arm, run). A trial is valid when every session in it
is valid and it reached its evaluation session; its outcome is the evaluation
session's outcome, and timeouts, failed hooks and missing answers count as
failures. A pair (task, run) enters a comparison only when both arms' trials
are valid. Calibration receipts are summarised separately and never scored.
The output is deterministic: the same receipts and parameters give the same
bytes.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from records import read_receipts, validate_receipt

TREATMENT = "memkernel"
REPORTED_DIAGNOSTICS = {  # receipt key: report column (FR-018); read for wiki_studio, counted for every arm
    "wiki_studio_nested_model_calls": "Bash calls running `wiki-studio ingest`/`query` (of all Bash calls)",
    "direct_wiki_writes": "Write/Edit calls under the wiki (of all Write/Edit calls)",
}
NESTED_MODEL_DIAGNOSTIC = "wiki_studio_nested_model_calls"
SECOND_TREATMENT = "wiki_studio"  # its own comparison, never in memkernel's label (FR-016)
GROUPS = ("lc-retain", "lc-reval", "lc-wiki", "lc-compact")
COMPACT_GROUP = "lc-compact"


@dataclass(frozen=True)
class Trial:
    run_id: str
    task_id: str
    group: str
    arm: str
    run_index: int
    valid: bool
    invalid_reason: str | None
    outcome: str | None
    tokens: dict[str, int]
    diagnostics: dict[str, tuple[int, int]]  # summed over the trial's sessions: (numerator, denominator)


def assemble(receipts: list[dict[str, Any]]) -> list[Trial]:
    """One trial per (run_id, chain_id); duplicate sessions are rejected rather than merged."""
    chains: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    seen: set[tuple[str, str, int]] = set()
    for receipt in receipts:
        key = (receipt["run_id"], receipt["chain_id"], receipt["position"])
        if key in seen:
            raise ValueError(f"duplicate receipt for run {key[0]}, chain {key[1]}, position {key[2]}")
        seen.add(key)
        chains[(receipt["run_id"], receipt["chain_id"])].append(receipt)
    trials = []
    for run_id, chain_id in sorted(chains):
        sessions = sorted(chains[(run_id, chain_id)], key=lambda r: r["position"])
        first, last = sessions[0], sessions[-1]
        invalid = next((r["invalid_reason"] for r in sessions if not r["valid"]), None)
        if invalid is None and last["stage"] != "evaluation":
            invalid = "evaluation_not_reached"
        outcome = None
        if invalid is None:
            # a timeout in any session is the trial's outcome (FR-015a)
            outcome = "timeout" if any(r["outcome"] == "timeout" for r in sessions) else last["outcome"]
        tokens = {key: sum(r["tokens"][key] for r in sessions) for key in first["tokens"]}
        diagnostics = {
            name: (
                sum(r.get("diagnostics", {}).get(name, {}).get("numerator", 0) for r in sessions),
                sum(r.get("diagnostics", {}).get(name, {}).get("denominator", 0) for r in sessions),
            )
            for name in REPORTED_DIAGNOSTICS
        }
        trials.append(
            Trial(
                run_id,
                first["task_id"],
                first["group"],
                first["arm"],
                first["run_index"],
                invalid is None,
                invalid,
                outcome,
                tokens,
                diagnostics,
            )
        )
    return trials


def _pct(numerator: int, denominator: int) -> str:
    return f"{numerator}/{denominator} ({100 * numerator / denominator:.0f}%)" if denominator else "0/0"


def _arm_table(trials: list[Trial], group: str, arms: list[str]) -> list[str]:
    lines = [
        "| Arm | Trials | Valid | Passed | Failed | Timeout | No answer | Invalid (reason: count) |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for arm in arms:
        rows = [t for t in trials if t.group == group and t.arm == arm]
        valid = [t for t in rows if t.valid]
        count = {o: sum(1 for t in valid if t.outcome == o) for o in ("passed", "failed", "timeout", "no_answer")}
        reasons: dict[str, int] = defaultdict(int)
        for t in rows:
            if not t.valid:
                reasons[str(t.invalid_reason)] += 1
        invalid = ", ".join(f"{k}: {v}" for k, v in sorted(reasons.items())) or "none"
        lines.append(
            f"| {arm} | {len(rows)} | {len(valid)} | {_pct(count['passed'], len(valid))} | {count['failed']} "
            f"| {count['timeout']} | {count['no_answer']} | {invalid} |"
        )
    return lines


def _pairs(trials: list[Trial], group: str, comparator: str, treatment: str = TREATMENT) -> dict[str, int]:
    index = {(t.run_id, t.task_id, t.run_index, t.arm): t for t in trials if t.group == group}
    counts = {"pairs": 0, "both": 0, "treatment_only": 0, "comparator_only": 0, "neither": 0, "pairs_removed": 0}
    keys = sorted({(t.run_id, t.task_id, t.run_index) for t in trials if t.group == group})
    for run_id, task_id, run_index in keys:  # pairs never cross runs
        treated = index.get((run_id, task_id, run_index, treatment))
        other = index.get((run_id, task_id, run_index, comparator))
        if treated is None or other is None:
            continue
        if not (treated.valid and other.valid):
            counts["pairs_removed"] += 1
            continue
        a, b = treated.outcome == "passed", other.outcome == "passed"
        counts["pairs"] += 1
        counts["both" if a and b else "treatment_only" if a else "comparator_only" if b else "neither"] += 1
    return counts


def _diagnostics_table(trials: list[Trial], group: str, arms: list[str]) -> list[str]:
    """Instruction diagnostics per arm over every trial of the group; a nested model is flagged, never hidden."""
    lines = [
        "| Arm | " + " | ".join(REPORTED_DIAGNOSTICS.values()) + " |",
        "|---|" + "---|" * len(REPORTED_DIAGNOSTICS),
    ]
    nested = 0
    for arm in arms:
        rows = [t for t in trials if t.group == group and t.arm == arm]
        if not rows:
            continue
        cells = []
        for name in REPORTED_DIAGNOSTICS:
            numerator = sum(t.diagnostics[name][0] for t in rows)
            cells.append(f"{numerator}/{sum(t.diagnostics[name][1] for t in rows)}")
            if name == NESTED_MODEL_DIAGNOSTIC:
                nested += numerator
        lines.append(f"| {arm} | " + " | ".join(cells) + " |")
    if nested:
        lines += [
            "",
            f"**Token accounting incomplete:** {nested} Bash call(s) in this group ran `wiki-studio ingest` or "
            "`query`, which start a model whose tokens are not in the receipts.",
        ]
    return lines


def _second_treatment_table(
    trials: list[Trial], group: str, comparators: list[str], params: dict[str, Any]
) -> list[str]:
    """wiki_studio against the primary comparators; its pairs never count toward memkernel's label."""
    minimum = int(params["min_valid_pairs_wiki_studio"])
    lines = [
        f"| {SECOND_TREATMENT} vs | Valid pairs | Both pass | {SECOND_TREATMENT} only | Comparator only "
        "| Neither | Pairs removed |",
        "|---|---|---|---|---|---|---|",
    ]
    counts = []
    for comparator in comparators:
        c = _pairs(trials, group, comparator, SECOND_TREATMENT)
        counts.append(c["pairs"])
        lines.append(
            f"| {comparator} (primary) | {c['pairs']} | {c['both']} | {c['treatment_only']} "
            f"| {c['comparator_only']} | {c['neither']} | {c['pairs_removed']} |"
        )
    if min(counts, default=0) < minimum:
        lines += [
            "",
            f"**{SECOND_TREATMENT} not measured:** fewer than {minimum} valid pairs against a primary comparator.",
        ]
    return lines


def render(receipts: list[dict[str, Any]], params: dict[str, Any]) -> str:
    measured = [r for r in receipts if r["phase"] == "measured"]
    calibration = [r for r in receipts if r["phase"] == "calibration"]
    trials = assemble(measured)
    arms = [a for a in params["arms"] if any(t.arm == a for t in trials)]
    primary, secondary = params["primary_comparators"], params["secondary_comparators"]
    min_inferential = int(params["min_pairs_inferential"])
    min_compact = int(params["min_valid_pairs_lc_compact"])

    out = [
        f"# {params['title']}",
        "",
        "**Maintainer-run supplemental evaluation.** These numbers come from memkernel's own lifecycle runner "
        "(`eval/lifecycle-suite/`), not from a third-party harness. Failures, nulls and invalid trials are reported.",
        "",
        "**What each arm keeps between sessions.** `memkernel` keeps only its memory store: its workspace is "
        "reset to the task fixture every session, unlike a real project where files persist too. `claude_md` "
        "keeps only its files, `fs_grep` only earlier transcripts, and `bare`, `placebo` and `protocol` nothing. "
        "The primary comparison is therefore the memory store alone against files alone, not memkernel against "
        "a typical project setup. `wiki_studio` (wiki-studio's command-line tool, told never to run "
        "its model-backed verbs; the diagnostics count any call that did) keeps nothing beyond the lc-wiki "
        "shared wiki and runs on lc-wiki only; it is compared with the same file-based arms in its own table, "
        "never with memkernel.",
        "",
        f"- Code-freeze SHA: `{params['code_sha']}`",
        f"- Preregistration commit: `{params['preregistration_commit']}`",
        f"- Release tag: `{params['tag']}`",
        f"- Model: `{params['model']}`",
        f"- Measured sessions: {len(measured)}; trials: {len(trials)}",
        "",
    ]
    labels = []
    for group in GROUPS:
        if not any(t.group == group for t in trials):
            out += [f"## {group}", "", "Not run in this release.", ""]
            continue
        out += [f"## {group}", "", *_arm_table(trials, group, arms), ""]
        out += [
            "| memkernel vs | Valid pairs | Both pass | memkernel only | Comparator only | Neither | Pairs removed |",
            "|---|---|---|---|---|---|---|",
        ]
        for comparator in [*primary, *secondary]:  # preregistered: an absent arm shows as 0 valid pairs
            c = _pairs(trials, group, comparator)
            kind = "primary" if comparator in primary else "secondary"
            out.append(
                f"| {comparator} ({kind}) | {c['pairs']} | {c['both']} | {c['treatment_only']} "
                f"| {c['comparator_only']} | {c['neither']} | {c['pairs_removed']} |"
            )
            if comparator in primary:
                labels.append(c["pairs"])
        if group == COMPACT_GROUP:
            smallest = min((_pairs(trials, group, c)["pairs"] for c in primary), default=0)
            if smallest < min_compact:
                out += ["", f"**Not measured:** fewer than {min_compact} valid pairs against a primary comparator."]
        if any(t.group == group and t.arm == SECOND_TREATMENT for t in trials):
            out += ["", *_second_treatment_table(trials, group, list(primary), params)]
        out += ["", *_diagnostics_table(trials, group, arms)]
        out.append("")
    if measured:
        measured_totals = {k: sum(r["tokens"][k] for r in measured) for k in TOKEN_CLASSES}
        out += [
            "## Token usage (measured)",
            "",
            f"- Tokens: input {measured_totals['input']}, cache write {measured_totals['cache_write']}, "
            f"cache read {measured_totals['cache_read']}, output {measured_totals['output']}",
            *_compaction_lines(measured),
            "",
            *_budget_by_arm(measured),
        ]
    inferential = bool(labels) and min(labels) >= min_inferential
    out += [
        "## Label",
        "",
        (
            "Inferential: every primary comparison has at least the preregistered minimum of valid pairs."
            if inferential
            else f"Descriptive: at least one primary comparison has fewer than {min_inferential} valid pairs."
        ),
        "",
    ]
    totals = {k: sum(r["tokens"][k] for r in calibration) for k in ("input", "cache_write", "cache_read", "output")}
    reasons: dict[str, int] = defaultdict(int)
    for r in calibration:
        if not r["valid"]:
            reasons[str(r["invalid_reason"])] += 1
    out += [
        "## Calibration (not scored)",
        "",
        f"- Sessions: {len(calibration)}",
        f"- Tokens: input {totals['input']}, cache write {totals['cache_write']}, "
        f"cache read {totals['cache_read']}, output {totals['output']}",
        *_compaction_lines(calibration),
        f"- Invalid sessions: {', '.join(f'{k}: {v}' for k, v in sorted(reasons.items())) or 'none'}",
        f"- Live compaction proven: {params.get('live_compaction_proven', 'not recorded')}",
        "- Calibration sessions are not graded; no pass/fail exists for them.",
        "",
        *_usage_ranges(calibration),
        *_budget_by_arm(calibration),
    ]
    return "\n".join(out)


TOKEN_CLASSES = ("input", "cache_write", "cache_read", "output")


def _usage_ranges(sessions: list[dict[str, Any]]) -> list[str]:
    """Per-arm, per-session min / median / max of each token class: the budget's range, not a point."""
    if not sessions:
        return []
    from statistics import median

    lines = [
        "| Arm | Sessions | " + " | ".join(f"{c} min / median / max" for c in TOKEN_CLASSES) + " |",
        "|---|---|" + "---|" * len(TOKEN_CLASSES),
    ]
    for arm in sorted({r["arm"] for r in sessions}):
        rows = [r for r in sessions if r["arm"] == arm]
        cells = []
        for cls in TOKEN_CLASSES:
            values = sorted(r["tokens"][cls] for r in rows)
            cells.append(f"{values[0]} / {_count(median(values))} / {values[-1]}")
        lines.append(f"| {arm} | {len(rows)} | " + " | ".join(cells) + " |")
    return [*lines, ""]


def _compaction_lines(sessions: list[dict[str, Any]]) -> list[str]:
    """The compaction estimate, the lc-compact compaction count, and any compaction that reported no estimate."""
    estimate = sum(r["compaction_tokens_estimate"] for r in sessions)
    compact_sessions = [r for r in sessions if r["group"] == COMPACT_GROUP]
    one_compaction = sum(1 for r in compact_sessions if len(r["stages"]["compactions"]) == 1)
    silent = sorted(
        (r for r in sessions if r["compaction_estimates_missing"] > 0),
        key=lambda r: (r["run_id"], r["chain_id"], r["position"]),
    )
    lines = [
        f"- Compaction calls, estimated input (sum of compact_boundary.pre_tokens; not in the tokens above; the "
        f"summaries' output is not recorded): {estimate}",
        f"- `{COMPACT_GROUP}` sessions with exactly one compaction: {one_compaction} of {len(compact_sessions)}",
    ]
    if silent:
        missing = sum(r["compaction_estimates_missing"] for r in silent)
        where = ", ".join(
            f"{r['run_id']} {r['chain_id']} position {r['position']} ({r['compaction_estimates_missing']})"
            for r in silent
        )
        lines.append(
            f"- **WARNING: {missing} compaction(s) in {len(silent)} session(s) recorded no estimate** (`pre_tokens` "
            f"missing or unreadable, so the estimate above undercounts): {where}"
        )
    return lines


def _budget_by_arm(sessions: list[dict[str, Any]]) -> list[str]:
    """Input-side tokens per arm: the receipts, the compaction estimate, and the two side by side, never merged.

    Billed figures come only from the Console, which the calibration record sets beside these.
    """
    if not sessions:
        return []
    lines = [
        "| Arm | Receipts: input + cache write + cache read | Compaction estimate (input only) "
        "| Receipts plus estimate |",
        "|---|---|---|---|",
    ]
    for arm in sorted({r["arm"] for r in sessions}):
        rows = [r for r in sessions if r["arm"] == arm]
        received = sum(r["tokens"]["input"] + r["tokens"]["cache_write"] + r["tokens"]["cache_read"] for r in rows)
        estimate = sum(r["compaction_tokens_estimate"] for r in rows)
        lines.append(f"| {arm} | {received} | {estimate} | {received + estimate} |")
    return [*lines, ""]


def _count(value: float) -> str:
    """A token count as digits, never in exponent form; a median of two counts may end in .5."""
    return f"{value:.0f}" if value == int(value) else f"{value:.1f}"


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Render the lifecycle report from receipts")
    parser.add_argument("--receipts", type=Path, action="append", required=True)
    parser.add_argument("--params", type=Path, required=True)
    args = parser.parse_args(argv)
    receipts = [r for path in args.receipts for r in read_receipts(path)]
    for receipt in receipts:
        errors = validate_receipt(receipt)
        if errors:
            print(f"invalid receipt {receipt.get('chain_id')}: {errors}", file=sys.stderr)
            return 1
    sys.stdout.write(render(receipts, json.loads(args.params.read_text(encoding="utf-8"))))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

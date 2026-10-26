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
import random
import sys
from collections import defaultdict
from dataclasses import dataclass
from fractions import Fraction
from math import ceil, comb
from pathlib import Path
from typing import Any

from estimate import load_parameters
from records import (
    AUTHENTICATION_ERROR,
    AUTHENTICATION_STATUSES,
    CALIBRATION_ONLY_SCHEMA_VERSION,
    read_receipts,
    sha256_bytes,
    validate_report_receipt,
)

TREATMENT = "memkernel"
REPORTED_DIAGNOSTICS = {  # receipt key: report column (FR-018); read for wiki_studio, counted for every arm
    "wiki_studio_nested_model_calls": "Bash calls running `wiki-studio ingest`/`query` (of all Bash calls)",
    "direct_wiki_writes": "Write/Edit calls under the wiki (of all Write/Edit calls)",
}
NESTED_MODEL_DIAGNOSTIC = "wiki_studio_nested_model_calls"
SECOND_TREATMENT = "wiki_studio"  # its own comparison, never in memkernel's label (FR-016)
GROUPS = ("lc-retain", "lc-reval", "lc-wiki", "lc-compact")
COMPACT_GROUP = "lc-compact"
# api_errors keys of an authentication refusal (FR-015a (c)); any other key is a non-authentication API error
AUTHENTICATION_KEYS = frozenset({*(str(status) for status in AUTHENTICATION_STATUSES), AUTHENTICATION_ERROR})
CONFIDENCE = 0.95  # the bootstrap interval's level (FR-016)
# What the analysis takes from the preregistration's parameter block, never from --params (FR-016)
PREREGISTERED = (
    "model",
    "arms",
    "primary_comparators",
    "secondary_comparators",
    "alpha",
    "no_gain_band_points",
    "bootstrap_resamples",
    "bootstrap_seed",
    "min_pairs_inferential",
    "min_tasks_inferential",
    "min_valid_pairs_lc_compact",
    "min_valid_pairs_wiki_studio",
)
LABEL_GAIN, LABEL_LOSS, LABEL_EQUIVALENT, LABEL_NONE = "gain", "loss", "equivalent", "no detectable difference"
DISAGREE = "the test's direction and the mean's sign disagree"  # FR-016, amended 2026-10-24 (second amendment)


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
    truncated: bool = False  # excluded by truncation (FR-015a): neither invalid nor scored

    @property
    def scored(self) -> bool:
        return self.valid and not self.truncated


def carries_api_error(receipt: dict[str, Any]) -> bool:
    """A non-authentication API error event in the session (FR-015a, Truncated run)."""
    return any(key not in AUTHENTICATION_KEYS for key in receipt.get("api_errors", {}))


def truncated_sessions(receipts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Each run's strict tail of sessions that carry a non-authentication API error, ordered by started_at across the
    run; a single later session without one leaves the run untruncated, and those errors stay scored."""
    by_run: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for receipt in receipts:
        by_run[receipt["run_id"]].append(receipt)
    tail: list[dict[str, Any]] = []
    for run_id in sorted(by_run):
        ordered = sorted(by_run[run_id], key=lambda r: (r["started_at"], r["chain_id"], r["position"]))
        start = len(ordered)
        while start > 0 and carries_api_error(ordered[start - 1]):
            start -= 1
        tail += ordered[start:]
    return tail


def assemble(receipts: list[dict[str, Any]], truncated: list[dict[str, Any]] | None = None) -> list[Trial]:
    """One trial per (run_id, chain_id); duplicate sessions are rejected rather than merged. A trial with any
    truncated session is excluded by truncation, whatever else it is."""
    cut = {(r["run_id"], r["chain_id"]) for r in truncated or []}
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
                (run_id, chain_id) in cut,
            )
        )
    return trials


def _pct(numerator: int, denominator: int) -> str:
    return f"{numerator}/{denominator} ({100 * numerator / denominator:.0f}%)" if denominator else "0/0"


def _arm_table(trials: list[Trial], group: str, arms: list[str]) -> list[str]:
    lines = [
        "| Arm | Trials | Valid | Passed | Failed | Timeout | No answer | Invalid (reason: count) | Truncated |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for arm in arms:
        rows = [t for t in trials if t.group == group and t.arm == arm]
        valid = [t for t in rows if t.scored]
        count = {o: sum(1 for t in valid if t.outcome == o) for o in ("passed", "failed", "timeout", "no_answer")}
        reasons: dict[str, int] = defaultdict(int)
        for t in rows:
            if not t.valid and not t.truncated:
                reasons[str(t.invalid_reason)] += 1
        invalid = ", ".join(f"{k}: {v}" for k, v in sorted(reasons.items())) or "none"
        truncated = sum(1 for t in rows if t.truncated)
        lines.append(
            f"| {arm} | {len(rows)} | {len(valid)} | {_pct(count['passed'], len(valid))} | {count['failed']} "
            f"| {count['timeout']} | {count['no_answer']} | {invalid} | {truncated} |"
        )
    return lines


def _pairs(trials: list[Trial], group: str, comparator: str, treatment: str = TREATMENT) -> dict[str, int]:
    index = {(t.run_id, t.task_id, t.run_index, t.arm): t for t in trials if t.group == group}
    counts = {
        "pairs": 0,
        "both": 0,
        "treatment_only": 0,
        "comparator_only": 0,
        "neither": 0,
        "pairs_removed": 0,
        "pairs_truncated": 0,
    }
    keys = sorted({(t.run_id, t.task_id, t.run_index) for t in trials if t.group == group})
    for run_id, task_id, run_index in keys:  # pairs never cross runs
        treated = index.get((run_id, task_id, run_index, treatment))
        other = index.get((run_id, task_id, run_index, comparator))
        if treated is None or other is None:
            continue
        if treated.truncated or other.truncated:  # even when the other trial ran before the tail (FR-015a)
            counts["pairs_truncated"] += 1
            continue
        if not (treated.valid and other.valid):
            counts["pairs_removed"] += 1
            continue
        a, b = treated.outcome == "passed", other.outcome == "passed"
        counts["pairs"] += 1
        counts["both" if a and b else "treatment_only" if a else "comparator_only" if b else "neither"] += 1
    return counts


def _group_mean_effect(trials: list[Trial], group: str, comparator: str, treatment: str = TREATMENT) -> str:
    """Descriptive only (FR-016): the mean per-task effect in percentage points over the group's tasks, no test."""
    effects, _ = task_effects([t for t in trials if t.group == group], comparator, treatment)
    return f"{float(100 * sum(effects.values()) / len(effects)):+.1f}" if effects else "n/a"


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
        "| Neither | Pairs removed | Pairs truncated | Mean effect (points, descriptive) |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    counts = []
    for comparator in comparators:
        c = _pairs(trials, group, comparator, SECOND_TREATMENT)
        counts.append(c["pairs"])
        lines.append(
            f"| {comparator} (primary) | {c['pairs']} | {c['both']} | {c['treatment_only']} "
            f"| {c['comparator_only']} | {c['neither']} | {c['pairs_removed']} | {c['pairs_truncated']} "
            f"| {_group_mean_effect(trials, group, comparator, SECOND_TREATMENT)} |"
        )
    if min(counts, default=0) < minimum:
        lines += [
            "",
            f"**{SECOND_TREATMENT} not measured:** fewer than {minimum} valid pairs against a primary comparator.",
        ]
    return lines


def sign_test(ahead: int, behind: int) -> float:
    """Exact two-sided sign test over the non-tied tasks: ``ahead`` favour the treatment, ``behind`` the comparator."""
    n = ahead + behind
    if n == 0:
        return 1.0
    tail = sum(comb(n, i) for i in range(min(ahead, behind) + 1))
    return min(1.0, 2 * tail / float(2**n))


def holm(pvalues: dict[str, float]) -> dict[str, float]:
    """Holm-adjusted p-values, ties broken by name so the result is deterministic."""
    adjusted: dict[str, float] = {}
    running = 0.0
    ordered = sorted(pvalues.items(), key=lambda item: (item[1], item[0]))
    for rank, (name, p) in enumerate(ordered):
        running = max(running, min(1.0, (len(ordered) - rank) * p))
        adjusted[name] = running
    return adjusted


def bootstrap_interval(effects: list[Any], resamples: int, seed: int) -> tuple[Any, Any]:
    """Percentile bootstrap interval of the mean over tasks, each task weighted equally; seeded, so deterministic.
    Given Fractions it is exact, so an interval at the band's edge is never pushed across it by rounding."""
    rng = random.Random(seed)
    n = len(effects)
    # int(rng.random() * n), not randrange or choice: only random()'s sequence is guaranteed across Python versions,
    # and the published interval must reproduce byte for byte (SC-8)
    means = sorted(sum(effects[int(rng.random() * n)] for _ in range(n)) / n for _ in range(resamples))
    tail = (1 - CONFIDENCE) / 2
    return means[int(tail * resamples)], means[ceil((1 - tail) * resamples) - 1]


def task_effects(trials: list[Trial], comparator: str, treatment: str = TREATMENT) -> tuple[dict[str, Fraction], int]:
    """Per task, the treatment's success rate minus the comparator's over the task's valid pairs (all groups pooled);
    a task without a valid pair is left out. Returns the effects, exact, and the number of valid pairs behind them:
    a mean that is exactly 0 must never come out positive or negative through floating-point rounding."""
    index = {(t.run_id, t.task_id, t.run_index, t.arm): t for t in trials}
    outcomes: dict[str, list[tuple[bool, bool]]] = defaultdict(list)
    for run_id, task_id, run_index in sorted({(t.run_id, t.task_id, t.run_index) for t in trials}):
        treated = index.get((run_id, task_id, run_index, treatment))
        other = index.get((run_id, task_id, run_index, comparator))
        if treated is not None and other is not None and treated.scored and other.scored:
            outcomes[task_id].append((treated.outcome == "passed", other.outcome == "passed"))
    effects = {
        task: Fraction(sum(a for a, _ in pairs) - sum(b for _, b in pairs), len(pairs))
        for task, pairs in outcomes.items()
    }
    return effects, sum(len(pairs) for pairs in outcomes.values())


def _primary_endpoint(trials: list[Trial], params: dict[str, Any]) -> tuple[list[str], bool]:
    """FR-016's analysis plan: the task as the unit, all tasks pooled, a sign test per primary comparator with Holm
    over them, the mean effect with an approximate bootstrap interval, and a label only when inferential."""
    primary = list(params["primary_comparators"])
    alpha, band = float(params["alpha"]), Fraction(str(params["no_gain_band_points"]))  # exact, like the effects
    resamples, seed = int(params["bootstrap_resamples"]), int(params["bootstrap_seed"])
    min_pairs, min_tasks = int(params["min_pairs_inferential"]), int(params["min_tasks_inferential"])
    rows: dict[str, dict[str, Any]] = {}
    for comparator in primary:
        effects, pairs = task_effects(trials, comparator)
        ahead = sum(1 for e in effects.values() if e > 0)
        behind = sum(1 for e in effects.values() if e < 0)
        values = [effects[task] for task in sorted(effects)]
        interval = bootstrap_interval([100 * e for e in values], resamples, seed) if values else None
        mean = 100 * sum(values) / len(values) if values else None
        rows[comparator] = {
            "tasks": len(effects),
            "pairs": pairs,
            "ahead": ahead,
            "behind": behind,
            "tied": len(effects) - ahead - behind,
            "p": sign_test(ahead, behind),
            "mean": mean,
            "interval": interval,
        }
    adjusted = holm({c: r["p"] for c, r in rows.items()})
    for r in rows.values():  # each primary comparison carries the inferential label on its own minimums (FR-016)
        r["eligible"] = r["pairs"] >= min_pairs and r["tasks"] >= min_tasks
    inferential = bool(rows) and all(r["eligible"] for r in rows.values())
    for comparator, r in rows.items():
        if not r["eligible"] or r["mean"] is None:
            r["label"] = "not applied (descriptive)"
        elif adjusted[comparator] < alpha:
            # the sign test says which arm more tasks favour, the mean by how much: a label needs both to agree
            if r["ahead"] > r["behind"] and r["mean"] > 0:
                r["label"] = LABEL_GAIN
            elif r["behind"] > r["ahead"] and r["mean"] < 0:
                r["label"] = LABEL_LOSS
            else:
                r["label"] = f"{LABEL_NONE} ({DISAGREE})"
        elif -band <= r["interval"][0] and r["interval"][1] <= band:
            r["label"] = LABEL_EQUIVALENT
        else:
            r["label"] = LABEL_NONE
    lines = [
        "## Primary endpoint (all tasks pooled)",
        "",
        f"The task is the unit: per task, memkernel's success rate minus the comparator's over its valid pairs. "
        f"Exact two-sided sign test over the non-tied tasks (tied tasks are left out and counted), Holm over the "
        f"{len(primary)} primary comparators at alpha {alpha}; mean effect in percentage points, each task weighted "
        f"equally, with a {CONFIDENCE:.0%} percentile bootstrap interval over tasks ({resamples} resamples, seed "
        f"{seed}; approximate at this number of tasks). Equivalent means the whole interval lies within "
        f"+/-{float(band):g} points.",
        "",
        "| memkernel vs | Tasks | Valid pairs | memkernel ahead | Comparator ahead | Tied | Sign test p "
        "| Holm-adjusted p | Mean effect (points) | Interval (points) | Label |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for comparator, r in rows.items():
        mean_text = "n/a" if r["mean"] is None else f"{float(r['mean']):+.1f}"
        interval_text = (
            "n/a" if r["interval"] is None else f"{float(r['interval'][0]):+.1f} to {float(r['interval'][1]):+.1f}"
        )
        lines.append(
            f"| {comparator} | {r['tasks']} | {r['pairs']} | {r['ahead']} | {r['behind']} | {r['tied']} "
            f"| {r['p']:.4f} | {adjusted[comparator]:.4f} | {mean_text} | {interval_text} | {r['label']} |"
        )
    gains = [c for c, r in rows.items() if r["label"] == LABEL_GAIN]
    if not any(r["eligible"] for r in rows.values()):
        headline = "no claim (descriptive: below the preregistered minimum; no test result is a finding)"
    elif rows and len(gains) == len(rows):
        headline = "gain against every primary comparator"
    else:
        headline = "no gain claimed (a gain needs every primary comparator labelled gain)"
    lines += [
        "",
        f"**Headline:** {headline}. Requiring every comparator to pass after Holm is deliberately stricter than an "
        "intersection-union test.",
        "",
        "Per-group tables below are descriptive: a group of five tasks cannot reach p < 0.05 with a sign test.",
        "",
    ]
    return lines, inferential


def _api_error_lines(sessions: list[dict[str, Any]], tail: list[dict[str, Any]], trials: list[Trial]) -> list[str]:
    """API error events per arm (events, not calls) and any truncated tail, listed (FR-015a, FR-018)."""
    per_arm: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    # FR-015a: sessions, not events, whose trial stayed scored: not invalid, not excluded by truncation
    scored = {(t.run_id, t.task_id, t.arm, t.run_index) for t in trials if t.scored}
    scored_with_errors: dict[str, int] = defaultdict(int)
    for r in sessions:
        for key, count in r.get("api_errors", {}).items():
            per_arm[r["arm"]][key] += count
        if carries_api_error(r) and (r["run_id"], r["task_id"], r["arm"], r["run_index"]) in scored:
            scored_with_errors[r["arm"]] += 1
    lines = [
        "## API errors (measured)",
        "",
        "Counts are error events, not failed calls: one refused call appears both as an assistant message and as a "
        "result, under two keys.",
        "",
    ]
    if per_arm:
        lines += [
            "| Arm | Error events (key: count) | Scored sessions with a non-authentication API error |",
            "|---|---|---|",
        ]
        for arm in sorted(per_arm):
            events = ", ".join(f"{k}: {v}" for k, v in sorted(per_arm[arm].items()))
            lines.append(f"| {arm} | {events} | {scored_with_errors[arm]} |")
    else:
        lines.append("- None.")
    if tail:
        lines += [
            "",
            f"**Truncated:** {len(tail)} session(s) at the end of their run carried a non-authentication "
            "API error, with none after them; they are listed, not scored, and their pairs are removed:",
        ]
        lines += [
            f"- {r['run_id']} {r['arm']} {r['task_id']} run {r['run_index']} position {r['position']} "
            f"({r['started_at']})"
            for r in tail
        ]
    else:
        lines += ["", "- Truncation: none."]
    return [*lines, ""]


def render(receipts: list[dict[str, Any]], params: dict[str, Any]) -> str:
    measured = [r for r in receipts if r["phase"] == "measured"]
    calibration = [r for r in receipts if r["phase"] == "calibration"]
    tail = truncated_sessions(measured)
    trials = assemble(measured, tail)
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
    endpoint, inferential = _primary_endpoint(trials, params)
    out += ["", *endpoint]
    for group in GROUPS:
        if not any(t.group == group for t in trials):
            out += [f"## {group}", "", "Not run in this release.", ""]
            continue
        out += [f"## {group}", "", *_arm_table(trials, group, arms), ""]
        out += [
            "| memkernel vs | Valid pairs | Both pass | memkernel only | Comparator only | Neither | Pairs removed "
            "| Pairs truncated | Mean effect (points, descriptive) |",
            "|---|---|---|---|---|---|---|---|---|",
        ]
        for comparator in [*primary, *secondary]:  # preregistered: an absent arm shows as 0 valid pairs
            c = _pairs(trials, group, comparator)
            kind = "primary" if comparator in primary else "secondary"
            out.append(
                f"| {comparator} ({kind}) | {c['pairs']} | {c['both']} | {c['treatment_only']} "
                f"| {c['comparator_only']} | {c['neither']} | {c['pairs_removed']} | {c['pairs_truncated']} "
                f"| {_group_mean_effect(trials, group, comparator)} |"
            )
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
        out += _api_error_lines(measured, tail, trials)
    min_tasks = int(params["min_tasks_inferential"])
    out += [
        "## Label",
        "",
        (
            f"Inferential: every primary comparison has at least {min_inferential} valid pairs covering at least "
            f"{min_tasks} tasks."
            if inferential
            else f"Descriptive: at least one primary comparison has fewer than {min_inferential} valid pairs or "
            f"covers fewer than {min_tasks} tasks."
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
        _calibration_api_errors(calibration),
        f"- Invalid sessions: {', '.join(f'{k}: {v}' for k, v in sorted(reasons.items())) or 'none'}",
        f"- Live compaction proven: {params.get('live_compaction_proven', 'not recorded')}",
        "- Calibration sessions are not graded; no pass/fail exists for them.",
        "",
        *_usage_ranges(calibration),
        *_budget_by_arm(calibration),
    ]
    return "\n".join(out)


TOKEN_CLASSES = ("input", "cache_write", "cache_read", "output")


def _calibration_api_errors(sessions: list[dict[str, Any]]) -> str:
    """Older calibration receipts did not record API errors: shown as unknown for them, never as 0 (FR-018)."""
    unknown = sum(1 for r in sessions if r["schema_version"] == CALIBRATION_ONLY_SCHEMA_VERSION)
    counts: dict[str, int] = defaultdict(int)
    for r in sessions:
        for key, count in r.get("api_errors", {}).items():
            counts[key] += count
    known = ", ".join(f"{k}: {v}" for k, v in sorted(counts.items())) or "none"
    if unknown:
        rest = f"; in the other {len(sessions) - unknown}: {known}" if unknown < len(sessions) else ""
        return (
            f"- API error events: unknown for {unknown} session(s) (schema version {CALIBRATION_ONLY_SCHEMA_VERSION} "
            f"receipts do not record them){rest}"
        )
    return f"- API error events: {known}"


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


def preregistered_params(
    params: dict[str, Any], preregistration: bytes, measured: list[dict[str, Any]]
) -> dict[str, Any]:
    """--params with the analysis taken from the preregistration's block: the measured receipts must name this
    file's sha256, the block must hold every PREREGISTERED key, and --params may not say otherwise."""
    digest = sha256_bytes(preregistration)
    named = sorted({str(r["preregistration_sha256"]) for r in measured} - {digest})
    if named:
        raise ValueError(f"measured receipts name preregistration sha256 {', '.join(named)}, not this file's {digest}")
    block = load_parameters(preregistration.decode("utf-8"))
    missing = [key for key in PREREGISTERED if key not in block]
    if missing:
        raise ValueError(f"the preregistration's parameters lack: {', '.join(missing)}")
    differ = [key for key in PREREGISTERED if key in params and params[key] != block[key]]
    if differ:
        raise ValueError(f"--params disagrees with the preregistration on: {', '.join(differ)}")
    _check_bindings(measured, block, str(params["code_sha"]))
    return {**params, **{key: block[key] for key in PREREGISTERED}}


def _check_bindings(measured: list[dict[str, Any]], block: dict[str, Any], code_sha: str) -> None:
    """Every measured receipt belongs to the preregistered experiment: its model, the code-freeze SHA, a
    preregistered task and arm, and a run index within the preregistered runs (FR-016, FR-017)."""
    tasks, arms, runs = set(block["tasks"]), set(block["arms"]), int(block["runs_per_arm_per_task"])
    problems: dict[str, set[str]] = defaultdict(set)
    for r in measured:
        if r["model"] != block["model"]:
            problems["model"].add(str(r["model"]))
        if r["code_sha"] != code_sha:
            problems["code_sha"].add(str(r["code_sha"]))
        if r["task_id"] not in tasks:
            problems["task"].add(str(r["task_id"]))
        if r["arm"] not in arms:
            problems["arm"].add(str(r["arm"]))
        if not 0 <= r["run_index"] < runs:
            problems["run_index"].add(str(r["run_index"]))
    if problems:
        found = "; ".join(f"{kind} {', '.join(sorted(values))}" for kind, values in sorted(problems.items()))
        raise ValueError(f"measured receipts outside the preregistered experiment: {found}")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Render the lifecycle report from receipts")
    parser.add_argument("--receipts", type=Path, action="append", required=True)
    parser.add_argument("--params", type=Path, required=True, help="title, SHAs and tag; the analysis is preregistered")
    parser.add_argument("--preregistration", type=Path, help="required whenever there are measured receipts")
    args = parser.parse_args(argv)
    receipts = [r for path in args.receipts for r in read_receipts(path)]
    for receipt in receipts:
        errors = validate_report_receipt(receipt)
        if errors:
            print(f"invalid receipt {receipt.get('chain_id')}: {errors}", file=sys.stderr)
            return 1
    params = json.loads(args.params.read_text(encoding="utf-8"))
    measured = [r for r in receipts if r["phase"] == "measured"]
    if measured and args.preregistration is None:
        print("measured receipts need --preregistration: the analysis is the preregistered one", file=sys.stderr)
        return 1
    if args.preregistration is not None:
        try:
            params = preregistered_params(params, args.preregistration.read_bytes(), measured)
        except ValueError as exc:
            print(f"report: {exc}", file=sys.stderr)
            return 1
    sys.stdout.write(render(receipts, params))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

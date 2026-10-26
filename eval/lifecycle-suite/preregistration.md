# Preregistration: memkernel 0.5 lifecycle evaluation (measured run)

The preregistration that FR-016 of `specs/memkernel-0-5/spec.md` requires
before the first measured session. It is committed on its own, directly after
the code freeze; its commit SHA and this file's sha256 are posted on
gosha70/memkernel#17 before any measured session (FR-016, FR-017, SC-5). The
report (`eval/lifecycle-suite/report.py`) reads its analysis parameters from the
block at the end of this file, and the measured run (`vm.sh measure`,
`run.sh measure`, `estimate.py`) reads its tasks, arms, runs, model, prices and
spend limit from the same block. Nothing below is tuned after this commit.
Deviations, if any, are disclosed in the report.

This is a **maintainer-run supplemental evaluation**: memkernel's own runner,
not a third-party harness.

## What runs

- **Code-freeze SHA:** `641a508a2289b2d20775e6d149a0bb47678d1621` (`main`,
  version `0.5.0rc1`, the merge of #51). The measured run's image is built from
  it; the receipts' `code_sha` is this SHA.
- **Model and provider:** `claude-sonnet-5-5`, through the Anthropic API, driven
  by Claude Code 2.1.288 inside the image.
- **Arms:** `bare`, `placebo`, `protocol`, `claude_md`, `fs_grep`, `memkernel`,
  `wiki_studio`, with the persistence rules and instructions frozen in
  `eval/lifecycle-suite/arms/*/config.frozen.json` at the freeze SHA.
  `wiki_studio` runs on `lc-wiki` only.
- **Tasks:** all 20 tasks in `eval/lifecycle-suite/tasks/`, five per group.
  Calibration was discarded wholesale, so it may share tasks with this run.
  - `lc-compact`: `lc-compact-alert-threshold`, `lc-compact-name-order`, `lc-compact-page-size`, `lc-compact-port`, `lc-compact-text-encoding`
  - `lc-retain`: `lc-retain-order-ids`, `lc-retain-retry-revised`, `lc-retain-rounding`, `lc-retain-separator-revised`, `lc-retain-utc-stamps`
  - `lc-reval`: `lc-reval-identity-casefold`, `lc-reval-log-masking`, `lc-reval-manifest-paths`, `lc-reval-rounding-moved`, `lc-reval-timeout-units`
  - `lc-wiki`: `lc-wiki-backoff`, `lc-wiki-feature-flags`, `lc-wiki-minor-units`, `lc-wiki-release-tags`, `lc-wiki-slugs`
- **Runs per arm per task:** 5. That is 625 chains and 1,100 sessions: 2
  sessions per chain in `lc-retain`, `lc-reval` and `lc-wiki`, 1 in
  `lc-compact`.
- **Order:** run index, then task (in the block's order), then arm (in the
  block's order); every arm of a task and run index runs before the next task.
  Fixed in `runner.py`, not randomised.
- **Calibration:** `calibration-20261024T033046Z`
  (`eval/lifecycle-suite/calibration/RECORD-2026-10-24.md`), whose receipts give
  the budget below. Live compaction was proven there (12 of 12), so
  `lc-compact` is measured.

## Validity of trials (FR-015a)

A measured trial is **valid** (scored; failures count as failures),
**invalid** (excluded, with a reason, counted per arm and reason) or
**excluded by truncation**.

- **Invalid**, in a complete run, only for: (a) a harness failure established
  from runner-side evidence before the agent could act (`session_not_started`,
  `mcp_not_connected`, `fixture_restore_failed`, `checker_crashed`); (b) for
  `lc-compact`, no compaction between the exposure and evaluation stages
  (`no_compaction_before_evaluation`); (c) the API refused the run's key at any
  step (`authentication_failed`: a result's `api_error_status` 401 or 403, or an
  assistant message's `error: authentication_failed`).
- **Incomplete record:** the report also excludes a trial whose recorded
  sessions are all valid but whose receipts lack its evaluation session, under
  the reason `evaluation_not_reached`, counted per arm with the invalid
  reasons. A complete run cannot produce one: the runner stops a chain early
  only after an invalid session, whose own reason then applies, and writes a
  chain's receipts only once the chain has ended, so an interrupted run leaves
  no receipts for its unfinished chain. The reason exists for a receipts file
  that is missing a chain's evaluation session; any such trial is a defect in
  the record, disclosed in the report, never an agent failure.
- **Excluded by truncation:** a run's strict tail of sessions, ordered by
  `started_at` across the run, each carrying a non-authentication API error
  event, with no session after it that does not. Those sessions are listed, not
  scored, and any trial that contains one is excluded. Non-authentication API
  errors that are not such a tail stay scored and are counted by arm.
- **Everything else is valid:** an agent timeout, a failed or missing hook, a
  wrong, partial or missing answer, a refusal by the model.
- A pair (task, run index) enters a comparison only when both trials are
  valid and neither is truncated; otherwise the pair is removed and counted.
- A trial is scored by its evaluation session's checker; a timeout in any of
  its sessions makes its outcome a timeout.

## Analysis (FR-016)

- **Unit of inference:** the task. For a task and a comparator, the effect is
  memkernel's success rate minus the comparator's, over that task's valid
  pairs; a task without a valid pair is left out of that comparison. Effects,
  means and intervals are computed exactly, as fractions of runs.
- **Primary endpoint:** all 20 tasks pooled, memkernel against each primary
  comparator, `claude_md` and `fs_grep` (the arms that carry state in files).
  - Exact two-sided sign test over the tasks whose effect is not zero; tied
    tasks are left out of the test and reported with their count.
  - Holm correction over the two primary comparators at alpha 0.05. That is the
    threshold; there is no separate effect-size threshold.
  - Estimate: the mean effect in percentage points, each task weighted equally,
    with a 95 percent percentile bootstrap interval over tasks. At 20 tasks the
    interval is approximate.
  - Bootstrap: the resampling unit is the task. Each of 10,000 resamples draws,
    with replacement, as many tasks as have a valid pair in that comparison,
    every task with equal weight, using Python's `random.Random(17)` and only
    its `random()` method, so every supported Python version gives the same
    draws. The interval is the 251st and the 9,750th of the 10,000 sorted
    resample means. No resample can fail: the effects are exact fractions, so
    every resample has a mean. When no task has a valid pair there is no
    interval (shown as n/a) and no label; when every task has the same effect
    the interval has zero width, which is a result, not a failure.
- **Labels, per primary comparator:**
  - **gain:** the Holm-adjusted test rejects, more non-tied tasks favour
    memkernel, and the mean effect is positive;
  - **loss:** the test rejects, more non-tied tasks favour the comparator, and
    the mean effect is negative;
  - a rejection whose direction and mean disagree, or whose mean is exactly
    zero: **no detectable difference**, with the disagreement stated;
  - no rejection: **equivalent** if the whole interval lies within the no-gain
    band of +/-10 percentage points, otherwise **no detectable difference**.
- **Headline:** a gain only when both primary comparators are labelled gain,
  deliberately stricter than an intersection-union test.
- **Smallest decisive result.** With Holm over two comparators, the smaller p
  must be below 0.025 and the larger below 0.05. Among non-tied tasks, that
  takes 16 of 20 (16 to 4) for p < 0.025 and 15 of 20 for p < 0.05; with 10
  non-tied tasks, 9 to 1 for either.
- **Inferential label:** a primary comparison carries a label only with at
  least 80 valid pairs covering at least 16 tasks. Below that it is
  descriptive: no label, and no test result is a finding. The headline makes no
  claim when no primary comparison qualifies.
- **Descriptive only, with no test:** per-group results (a group of five tasks
  cannot reach p < 0.05 with a sign test, whose best two-sided p is 0.0625);
  the secondary comparisons against `bare`, `placebo` and `protocol`; and
  `wiki_studio` against `claude_md` and `fs_grep` on `lc-wiki`, in its own
  table. `wiki_studio` does not enter memkernel's endpoint or label, and no
  memkernel-versus-`wiki_studio` claim is made.
- **Minimums for reporting a group as measured:** `lc-compact` needs at least
  10 valid pairs against each primary comparator; the `wiki_studio` comparison
  needs at least 10 valid pairs against each primary comparator. Below that, it
  is reported as not measured.
- **API errors:** error events per arm (events, not calls), and per arm the
  scored sessions that carried a non-authentication API error.

## Budget and spend (FR-015, FR-016)

- **Prices** (Claude Sonnet 5.5, USD per million tokens, from
  https://platform.claude.com/docs/en/about-claude/pricing on 2026-10-26):
  input 2.00, cache write 2.50 (5-minute), cache read 0.10, output 10.00. The
  compaction estimate is priced as input.
- **Estimate**, computed by `estimate.py` from the committed calibration
  receipts as mean cost per chain per group, scaled to this run, plus 20
  percent for invalid trials (paid, never retried): `lc-compact` 150 chains,
  $34.53; `lc-retain` 150 chains, $10.33; `lc-reval` 150 chains, $9.66;
  `lc-wiki` 175 chains, $12.76; subtotal $67.28; **total $80.74**. The
  calibration priced this way came to $4.07 against the Console's $3.50, so the
  method errs high.
- **Spend limit:** $150, the monthly spend limit of a dedicated Claude Console
  workspace created for this run (approved by the owner on 2026-10-24),
  verified in the Console before the first session. `run.sh measure` refuses to
  start when the limit typed is not $150 or when the estimate plus 30 percent
  ($104.96) exceeds it.

## Isolation (FR-015, FR-018)

The measured run uses the calibration's isolation: a throwaway local Lima VM
with no shared folders, no SSH agent and no personal credentials; the host
block (no route to the Mac or the LAN, proven by probes before the key is
asked for); a new key scoped to the dedicated workspace only, deleted and the
workspace archived afterwards. Before `measure`, the wiki-bridge wiring check
(task 18a) is re-run on the measured run's image and its image ID recorded.
Only `receipts.jsonl` is committed, after the operator's review and the secret
scan; raw streams stay outside any git checkout.

## Parameters

```json
{
  "model": "claude-sonnet-5-5",
  "tasks": [
    "lc-compact-alert-threshold",
    "lc-compact-name-order",
    "lc-compact-page-size",
    "lc-compact-port",
    "lc-compact-text-encoding",
    "lc-retain-order-ids",
    "lc-retain-retry-revised",
    "lc-retain-rounding",
    "lc-retain-separator-revised",
    "lc-retain-utc-stamps",
    "lc-reval-identity-casefold",
    "lc-reval-log-masking",
    "lc-reval-manifest-paths",
    "lc-reval-rounding-moved",
    "lc-reval-timeout-units",
    "lc-wiki-backoff",
    "lc-wiki-feature-flags",
    "lc-wiki-minor-units",
    "lc-wiki-release-tags",
    "lc-wiki-slugs"
  ],
  "arms": [
    "bare",
    "placebo",
    "protocol",
    "claude_md",
    "fs_grep",
    "memkernel",
    "wiki_studio"
  ],
  "runs_per_arm_per_task": 5,
  "primary_comparators": [
    "claude_md",
    "fs_grep"
  ],
  "secondary_comparators": [
    "bare",
    "placebo",
    "protocol"
  ],
  "alpha": 0.05,
  "no_gain_band_points": 10,
  "bootstrap_resamples": 10000,
  "bootstrap_seed": 17,
  "min_pairs_inferential": 80,
  "min_tasks_inferential": 16,
  "min_valid_pairs_lc_compact": 10,
  "min_valid_pairs_wiki_studio": 10,
  "prices_usd_per_mtok": {
    "input": 2.0,
    "cache_write": 2.5,
    "cache_read": 0.1,
    "output": 10.0
  },
  "prices_as_of": "2026-10-26",
  "invalid_allowance": 0.2,
  "calibration_receipts": "eval/lifecycle-suite/calibration/receipts-20261024T033046Z.jsonl",
  "spend_limit_usd": 150
}
```

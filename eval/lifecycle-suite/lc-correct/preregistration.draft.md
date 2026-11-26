# Preregistration draft: the lc-correct comparison (#90, #17)

**Status: draft, not approved.** Approving this file authorizes no paid run. The calibration and the measured run
each need a preregistration and a budget the owner approves (specs/memkernel-0-16-lifecycle-corrections D5). Items
marked **Owner** are open decisions; the rest follows the approved spec.

## Hypotheses

- **Primary.** Against the negative control (`bare`), each of `memkernel`, `memkernel_governed`, `fs_grep` and
  `claude_md` answers the corrected rule (Y) on more chains than it answers less often than `bare` does.
- **Secondary, descriptive.** `memkernel_governed` against `memkernel` (what the governed composition adds);
  `memkernel_governed_oracle` against `memkernel_governed` (curator error); the obsolete-answer rate (X) per arm,
  and for `memkernel` split by correction kind (replacement, withdrawal; D4). Gate breaches per governed arm.
- No claim of gain from the calibration.

## Arms (D2, D3)

`memkernel`, `memkernel_governed` (scripted curator, primary composition arm), `memkernel_governed_oracle` (upper
bound, descriptive only), `fs_grep`, `claude_md`, `bare`. `claude_md` stays unless the budget rules it out (D2).
`protocol`, `placebo` and the frozen 0.4.1 `wiki_studio` are left out. `auto_approve_on_promote` is not run (D3).
Each arm is pinned by its `config.frozen.json` hash, which covers its instruction and, for the governed arms, the
curator policy's sha256.

## Task set (FR-001, FR-003, D7)

The 12 `lc-correct` chains under `eval/lifecycle-suite/tasks/lc-correct-*`, six replacements and six withdrawals.
Every prompt is in the chain's `task.json`, recorded here by the task directory's hash at the preregistration commit.

- **Calibration first:** every chain runs with `bare` and `informed` only (decision B3), graded.
  `qualify.py --receipts <calibration receipts> --out calibrated.json` decides which chains enter the measured set.
  A chain enters only if every valid `bare` trial misses Y and every valid `informed` trial answers it.
- **Freezing:** the calibrated set, `calibrated.json` and the receipts' sha256 are committed before the measured run.
- **Too few chains:** if calibration leaves too few chains for the difference named below, the measured run is not
  paid for. The chain set is extended first (D7).

## Checkers

`correct_checker.py` with each chain's hidden `oracles/<task>/answers.json` (amendment A1). The evaluation prompt
asks for `ANSWER.md` whose `Answer:` line gives the value in a neutral form per chain (for example
`<weekday>; <HH:MM> UTC`), parts separated by `;`. Only that line is graded: it is `informed` when every part meets
the corrected rule's condition, `obsolete` when the parts meet the old rule's, and `other` otherwise, a missing,
unparsable or incomplete line included. A part with a negation or a qualifier (`not`, `no longer`, `at most`,
`instead of`, `was`, and the like) is unparsable, except a yes/no part's own yes or no. So are a time with am or pm
and an answer with more than one `Answer:` line. Each receipt records why an answer is `other` (`no_line`,
`unreadable`, `wrong_value`), and the report counts each reason per arm. The explanation below it may name both values; it decides nothing. Every
chain carries three adversarial references (the corrected rule only in prose; the old rule on the line with the
new one in prose; the line with extra parts), pinned to other, obsolete and other. There is no LLM judge.

## Model and versions (Owner)

- **Model:** the exact model ID.
- **Claude Code CLI:** the version.
- **memkernel:** the code SHA the run uses (`--code-sha`).
- **wiki-studio:** pinned at 0.10.0 by the governed arms' `cli_pin` and installed in the image.
- **Embedding model:** the pinned cache, as in the 0.5 image.

## Trials per chain and the smallest detectable difference (FR-006)

- **Runs per chain per arm (Owner):** `R`. This draft proposes R = 3.
- **A chain's verdict against `bare`:** the arm wins the chain when it passes more of its R trials than `bare`
  passes of its own, loses it when it passes fewer, and ties otherwise. Ties are left out of the test.
- **The test:** an exact two-sided sign test over the non-tied chains (`report.sign_test`), with Holm's correction
  across the four primary comparisons at α = 0.05. The smallest p-value must therefore be at most 0.0125. The
  oracle arm is descriptive and is not one of the four, so it does not enter the correction.

Exact two-sided p-values when every chain is non-tied:

| Chains | Chains favouring one arm, and the p-value |
|---|---|
| 12 | 12: 0.0005; 11: 0.0063; 10: 0.0386; 9: 0.146 |
| 11 | 11: 0.0010; 10: 0.0117; 9: 0.0654 |
| 10 | 10: 0.0020; 9: 0.0215; 8: 0.109 |
| 9 | 9: 0.0039; 8: 0.0391 |
| 8 | 8: 0.0078; 7: 0.0703 |

**The smallest difference the design can detect:**
- With 12 qualified chains, an arm must win at least 11 of them for its comparison to pass Holm's first step.
- With 11 chains, it must win at least 10. With 8, 9 or 10 chains, it must win every one. With 7 or fewer, no
  comparison can pass Holm's first step (7 of 7 gives p = 0.0156).
- More runs per chain sharpen each chain's verdict but do not change these counts.

**Stop rule (Owner):** with fewer than 8 qualified chains, no primary comparison can pass, so the run is not paid
for and the chain set is extended first (D7). With 8 to 10 chains, every chain must be won, and the owner decides
whether to run or to extend first.

## Exclusions

- **Invalid trials:** an invalid trial is removed with its pair, never scored. The reasons are the runner's,
  including `correction_failed` and `gate_check_failed`. Removed pairs are reported per arm.
- **Timeouts:** a timeout is a valid failure (`other`).
- **Truncated runs:** truncation follows the 0.5 rule (FR-015a).

## Report

`report.py` has an lc-correct section with each arm's informed, obsolete and other counts, the obsolete-answer
rate, invalid and truncated trials, gate breaches, and the pairs against `bare`. It also has the per-group token
table (FR-005). **The primary endpoint is not implemented yet:** `_primary_endpoint` fixes the treatment as
`memkernel`. Before the measured run it must be generalized to the four treatments above, each against `bare`, as
one Holm family, with the chain verdicts defined here. The measured run's report answers #17's remaining question
(D6).

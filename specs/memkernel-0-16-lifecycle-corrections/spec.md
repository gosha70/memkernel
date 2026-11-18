# Spec: a lifecycle task set that can tell the arms apart, and a governed-composition arm (#90, #17)

Status: draft, 2026-11-18. Written overnight on the owner's instruction to open a PR per issue; D1–D7 are
**proposed, for the owner's decision**, and nothing here is built yet. The design is wiki-studio's
(`eval/composition/design.md` at `b99484a`, filed as #90); this spec turns it into memkernel's requirements. No
measured run happens without a preregistration and a budget the owner approves (D5).

## Checked facts (`main` at `4ef72c2`)

- **The 0.5.0 `lc-wiki` group is at ceiling**: every arm passed 25 of 25 (`report-0.5.0.md`), and #17's result
  comment reports "no gain is claimed", with only `lc-retain` and `lc-reval` separating the arms.
- **The runner carries the answer into every arm.** `runner.py:199-203` copies a task's `shared_artifact` from the
  source session into the destination workspace; each arm's frozen config states it ("lc-wiki tasks: the task's
  shared_artifact directory ... is copied into the destination workspace for every arm (FR-012)").
- **Withdrawal shipped** (memkernel 0.7, `MemoryService.withdraw`), so #90's dependency 6 is met: a correction can
  replace or withdraw a decision.
- **The governed composition exists:** `memkernel[wiki]` requires wiki-studio 0.7 or later; the export → review →
  promote → approve → governed import loop is memkernel-0-7-governed.
- **Arms on disk:** `bare`, `claude_md`, `fs_grep`, `memkernel`, `placebo`, `protocol`, and the frozen 0.4.1
  `wiki_studio`. Frozen arm files are never edited; a version change is a new arm (#90 §3.1).

## User Scenarios

1. A maintainer runs the calibration and sees, per task, that the negative control fails and an informed reference
   passes, before any measured session.
2. The measured run reports, per arm, the share of trials answering the obsolete rule (X), the corrected rule (Y)
   and anything else, with paired comparisons against the negative control.
3. For the composition arm, every page it landed is matched to the gate's receipt and approval records; a page
   without them is a counted breach.

## Requirements

- **FR-001 The `lc-correct` group (D1).** Eight task chains from #90 §2.2 (deploy window, token lifetime, cache
  invalidation, retry policy, backup retention, access review cadence, feature-flag cleanup, invoice rounding).
  Session 0 records X; a correction between sessions changes the rule to Y; session 1 asks for the current rule
  without naming the correction, its value or its page. The checker has three outcomes: X fails as obsolete, Y
  passes, anything else fails. **An answer that names both values passes when Y is there** ("it was X; now it's
  Y" is correct), and one with X alone is obsolete. A fixture pins each case. The stated limit is that an answer
  naming both without saying which holds also passes. Each fixture wiki has at least one competing page carrying X.
- **FR-002 Corrections through the arm's own workflow.** A task's correction is an event the runner delivers per
  arm: for `memkernel`, through its correction path (a superseding retain, or `withdraw`, per the chain); for the
  composition arm, through export, curator, promote, approve and governed import; for `fs_grep`, a curator's
  direct edit of the files; for `bare`, nothing. The `shared_artifact` copy carries only the exposure state,
  never the correction (a new task field names what may be shared).
- **FR-003 Calibration first.** Every chain runs with `bare` and with an informed reference (Y supplied outside any
  arm). A chain enters the measured set only if `bare` fails and the reference passes; the calibrated set and its
  report are frozen before a measured run.
- **FR-004 The composition arm (D2, D3).** A new versioned arm, `memkernel_governed`, pinned to its wiki-studio and
  memkernel versions, with a scripted curator under a preregistered, hashed policy (#90 §3.3), and an oracle curator
  run beside it as the upper bound. The gate-record check of #90 §3.4 runs on its end state; breaches are counted
  in its result.
- **FR-005 A per-group token table** in the report, so costs compare within a group (#90 dependency 3).
- **FR-006 The preregistration and budget** (D5): hypotheses, arms, the calibrated set, checkers, model and
  versions, exclusions, the analysis, and the cost, frozen and approved before the measured run.
  - **It also states the trials per chain and the smallest difference the design can detect,** before anything
    is paid for.
  - **The arithmetic** for the 0.5 suite's primary test, an exact sign test over chains (two-sided):

    | Chains | Chains favouring one arm, and the p-value |
    |---|---|
    | 8 | 8 → 0.008; 7 → 0.07 |
    | 12 | 11 → 0.006; 10 → 0.04 |
    | 16 | 14 → 0.004; 13 → 0.02 |

  - **With eight chains, only a difference that nearly every chain shows can reach 0.05,** and less than that after
    a correction for several comparisons. More trials per chain sharpen each chain's verdict, but not the count of
    chains.
  - **If calibration leaves too few chains for the difference the preregistration names,** the run is not paid for.
    The chain set is extended first (D7).

## Constraints / What NOT to Build

- No edit to any frozen arm file or recorded run; the 0.4.1 `wiki_studio` arm stays historical.
- No LLM judge: the checkers are executable (#17's request, kept by the 0.5 suite).
- No measured or calibration run in the build PR: both need paid model calls and the owner's approval (D5).
- No claim of gain from calibration (it qualifies the set only).

## Key Entities

- **Chain:** one task's exposure, correction and evaluation, with its X and Y references and competing pages.
- **Correction event:** how a chain's change reaches the next session, per arm.

## Success Criteria

- **SC-1** Each chain's naive reference (X) fails and informed reference (Y) passes in CI, as the suite requires of
  every task today; fixtures pin an answer naming both values (passes) and one naming X alone (obsolete).
- **SC-2** In a stub-agent run, the runner delivers each arm's correction through its own path, and the
  `shared_artifact` copy never contains Y.
- **SC-3** The gate-record check flags a page landed without a receipt or an approval, on a fixture.
- **SC-4** The report has a per-group token table.
- **SC-5** The suite's own tests, ruff and mypy pass.

## Decisions (proposed, for the owner)

- **D1 Adopt #90's requirements and its eight chains** as the `lc-correct` group. Recommended.
- **D2 Arms for this comparison:** `memkernel`, `memkernel_governed` (with the oracle curator as an upper bound),
  `fs_grep`, **`claude_md`** and `bare`. `claude_md` stays: writing a corrected rule into CLAUDE.md is the most
  common real-world way to handle a correction, so it is the comparison readers will ask about. `protocol` and
  `placebo` are left out. Recommended, unless cost rules `claude_md` out (the budget, D5, says).
- **D3 The scripted curator** with a preregistered policy is the primary composition arm; `auto_approve_on_promote`
  is at most a named sensitivity check, not run by default. Recommended, as #90 argues.
- **D4 Both correction kinds:** replacement and withdrawal, now that 0.7 shipped withdrawal; the obsolete-answer rate
  covers both. Recommended.
- **D5 Two steps:** this spec's build ships the tasks, the runner change, the arm, the curator and the gate check,
  all exercised with the stub agent in CI. The calibration and the measured run come after, each with a
  preregistration and a budget you approve. Recommended.
- **D6 #17:** the measured run's report answers #17's remaining question (scenarios that can separate the arms).
  Close #17 when that report is published. Recommended.
- **D7 The chain count:** keep #90's eight chains if the preregistration's detectable difference is acceptable at
  that size; otherwise write more chains to the same requirements (#90 §2.1) before the calibration, toward 12 or
  16. Recommended: decide with the preregistration, from FR-006's arithmetic.

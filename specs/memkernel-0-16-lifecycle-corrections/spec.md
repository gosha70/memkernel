# Spec: a lifecycle task set that can tell the arms apart, and a governed-composition arm (#90, #17)

Status: approved by the owner, 2026-11-19: D1–D7 as written below, with 12 chains planned (D7) and `claude_md` an
arm unless the budget rules it out (D2). **Approving this spec authorizes no paid run:** the calibration and the
measured run each need a preregistration and a budget the owner approves. Drafted overnight on 2026-11-18; nothing
here is built yet. The design is wiki-studio's
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

- **FR-001 The `lc-correct` group (D1, D7).** Twelve task chains: the eight from #90 §2.2 (deploy window, token lifetime, cache
  invalidation, retry policy, backup retention, access review cadence, feature-flag cleanup, invoice rounding), and
  four more written to the same requirements (#90 §2.1) before the calibration (D7). Session 0 records X; a correction between sessions changes the rule to Y; session 1 asks for the current rule
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

## Decisions (the owner's, 2026-11-19)

- **D1 Adopt #90's requirements and its eight chains** as the `lc-correct` group, extended to 12 by D7.
- **D2 Arms for this comparison:** `memkernel`, `memkernel_governed` (with the oracle curator as an upper bound),
  `fs_grep`, **`claude_md`** and `bare`. `claude_md` stays: writing a corrected rule into CLAUDE.md is the most
  common real-world way to handle a correction, so it is the comparison readers will ask about. `protocol` and
  `placebo` are left out. `claude_md` stays unless the budget (D5) rules it out.
- **D3 The scripted curator** with a preregistered policy is the primary composition arm; `auto_approve_on_promote`
  is at most a named sensitivity check, not run by default, as #90 argues.
- **D4 Both correction kinds:** replacement and withdrawal, now that 0.7 shipped withdrawal; the obsolete-answer rate
  covers both.
- **D5 Two steps:** this spec's build ships the tasks, the runner change, the arm, the curator and the gate check,
  all exercised with the stub agent in CI. The calibration and the measured run come after, each with a
  preregistration and a budget the owner approves; approving this spec authorizes no paid run.
- **D6 #17:** the measured run's report answers #17's remaining question (scenarios that can separate the arms).
  Close #17 when that report is published.
- **D7 The chain count: plan on 12 chains.** Eight reach significance only when every chain favours one arm (FR-006's
  arithmetic: 8 of 8 gives p ≈ 0.008, 7 of 8 p ≈ 0.07; with 12, 10 of 12 gives p ≈ 0.04). The four added chains
  follow #90 §2.1 and are written before the calibration; the preregistration states the final count.

## Build decisions (2026-11-25)

B1–B4 are the owner's answers to the questions the build put before writing code. B5–B9 were made in the build and
are listed for review.

- **B1 claude_md (owner).** A scripted curator appends the chain's correction brief to `CLAUDE.md` in the workspace
  the arm carries, creating the file if session 0 did not. FR-002 had no path for this arm, which D2 added.
- **B2 Governed import (owner).** The runner runs memkernel's governed `wiki_import` as the last step of the
  correction event, after the curator approves. FR-002 lists the import as part of delivery.
- **B3 Calibration (owner).** A calibration-only arm, `informed`: `bare` plus the correction brief in its instruction,
  only in the sessions after the correction. An lc-correct calibration runs and grades only `bare` and `informed`.
  Measured arms never run in it, so nothing about them is seen before the preregistration. The runner refuses any
  other arm in such a calibration, and `informed` in a measured run.
- **B4 Correction kinds (owner).** Six replacements and six withdrawals, applied in the `memkernel` arm.
  - **Replacement:** retain Y with `supersedes` on the first live record carrying X, and supersede the rest by it.
  - **Withdrawal:** withdraw every record carrying X (`deprecated`), then retain Y unlinked.
  - **Other arms:** one path each; the governed arms correct through `corrects:`.
- **B5 The answer.** The evaluation session writes `ANSWER.md`. `correct_checker.py` classifies it by the chain's
  hidden patterns (`oracles/<task>/answers.json`): Y first, then X, else other. No candidate code runs.
- **B6 The oracle curator is its own arm,** `memkernel_governed_oracle`, so its receipts carry their own arm name and
  config hash.
- **B7 What the governed arms carry.** The store and the exposure wiki, as `memkernel` does, plus
  `doc_internal/proposals` (the gate's receipts), so the end-state check can find them. Both sessions use one memkernel
  namespace: the correction happens in the same project.
- **B8 Gate breaches.**
  - **A breach** is a landed content page without a committed receipt, or a non-draft page without an approval at
    its live sha256.
  - **Drafts:** a draft memkernel exported through the gate that nobody approved is counted separately, as an
    unreviewed draft. `approve` refuses drafts, and governed import never reads them.
  - **Lint:** violations on the end state are counted alongside.
- **B9 The receipt schema stays at version 3.** The change is additive: optional `answer_class`, `correction` and
  `gate`, and wider `arm`, `group` and `invalid_reason` enums (`correction_failed`, `gate_check_failed`). Receipts
  written before it, the committed 0.5 ones included, still validate.

**Found in the build:** an obsolete pattern written as `\bfriday\b` missed the competing page's "Fridays". The
test that every fixture's competing page matches its chain's obsolete patterns caught it, and the patterns now
accept the plural. Two chains' competing pages stated the old rule but not its answer; they now carry the obsolete
answer as well.

## Review amendments (2026-11-25)

Two reviews of the unpushed build, which the owner pasted, found what follows. A1 and A2 are the owner's choices
between the options put to them; the rest are fixes within the spec.

- **A1 The answer line (owner; replaces B5 and amends FR-001).**
  - **What failed:** the free-text checker passed wrong answers that merely contained Y ("Monday is explicitly not
    allowed"; "The limit is not 120; all 300 requests are accepted"), and multi-part answers could omit a part.
  - **The answer:** the evaluation prompt asks for an `Answer:` line in a neutral form per chain that reveals
    nothing of Y (for example `<weekday>; <HH:MM> UTC`), parts separated by `;`.
  - **Grading:** each part is parsed and compared with the hidden conditions. All of them meet Y's: `informed`.
    The parts meet X's: `obsolete`. Anything else is `other`, including a missing, unparsable or incomplete line.
  - **Both values:** the explanation below the line may name both values; the line decides. FR-001's stated limit
    (both values without saying which holds) no longer exists.
  - **Fixtures:** every chain has three adversarial references, each pinned to its class: Y only in prose (other),
    X on the line with Y in prose (obsolete), and the line with extra parts (other).
  - **Stricter reading (the owner, 2026-11-26):**
    - A part carrying a negation or a qualifier (`not`, `n't`, `no longer`, `except`, `never`, `under`, `over`,
      `at most`, `at least`, `instead of`, `was`, `previously`) is unparsable, so the answer is `other`. Only a
      yes/no part's leading `yes` or `no` is the answer itself.
    - A time with am or pm is refused, and more than one `Answer:` line is `other`.
    - Each form says what it wants (`in digits`, `a number with a unit`, `or 0 if none`, `24-hour`), and a
      hyphenated unit (`15-minute`) is read as `15 minute`.
    - Every reviewer probe is pinned in `tests/fixtures/lc-correct/probes.json` with its source.
- **A2 Blinding (owner: separate users).**
  - **The image:** the container starts as root. `/opt/memkernel` (tasks, corrections, oracles, references) is
    root's alone; memkernel is installed in `/opt/mk-venv`. Each session runs as an unprivileged `agent` user
    through `setpriv`, with the hook scripts, the ledger and the stub agent from the world-readable
    `/opt/agent-tools`. The image build fails if `agent` can list `/opt/memkernel`.
  - **The runner:**
    - Each session is prepared in its chain's folder, then run in `sessions/<random>/`, which names neither the
      task nor the arm and has nothing of the chain beside it (no `../../s0`). Its store, the store's state and
      the grep directory come with it.
    - With `--agent-uid`, the session's files are the agent's only while it runs; then they return to the chain.
    - Chain folders are mode 0700, the run folder 0711 and the receipts 0600, all the harness's.
    - On a rootful Docker host, `RUNS_OWNER` makes `run.sh` hand the finished run to whoever copies it off. Lima's
      rootless Docker needs none: the container's root is the VM user.
    - A calibration or measured run refuses to start outside the isolated image, before it creates anything. It
      requires root, the `agent` and `grader` users named by the run, and a read attempt as `agent` that fails on
      the repository, the tasks and the oracles.
  - **The probe:** the demo's stub agent records what it can reach (the sessions folder, the run folder, `../../s0`,
    the oracles). The demo fails unless its own session is all it sees. In the image, where the agent is a separate
    user, it also fails unless the run folder and the oracles are unreadable.
  - **Processes:** each step runs in its own process group, killed when the step ends. In the image, when the
    session ends, every process of the agent user is killed with `setpriv --reuid=<uid> -- kill -KILL -1` (procps's
    `kill`, installed for this). `/proc` is then checked, and a session with any live survivor is invalid
    (`agent_processes_survived`). Grading does the same for the grader, and a survivor there is an infrastructure
    error (`checker_crashed`). The probe leaves one process in the group and one detached from
    it, and the demo fails if either survives (outside the image the detached one can escape, and is only cleaned
    up).
  - **Grading:** in the image the candidate's code runs as a second unprivileged user, `grader`, from a copy of the
    oracle driver, and its processes are killed afterwards. The demo's grading probe must report that uid.
  - **Hooks:** in the image the demo runs the memkernel arm's real hook scripts as the agent user, against the
    pinned model cache, and fails unless every hook exits 0 and all three ran. This is the owner's ready gate for
    PR #166, with the probe.
- **A3 The rest of the review.**
  - **Gate check:** also requires each covering receipt's audit archive (`plan.json` matching the receipt's
    `plan_sha256`, `proposal.md`, and `curator-delta.md` when the receipt shows a hand edit). The `gate` field has
    a fixed shape.
  - **Curator CLI:** a paid run resolves it to one absolute path, checks that file's version against the pin, and
    invokes only it.
  - **`qualify.py`:** requires the exact `12 × 2 × R_cal` manifest; a missing, unexpected or duplicated chain is
    refused. It and the report also refuse a chain whose sessions do not start at position 0 or skip one.
  - **Stale-base retry:** re-renders the corrected page from the fresh read; the scripted policy says so and its
    hash is re-pinned.
  - **Helper failures:** helpers have a timeout, and unreadable helper output is `correction_failed`, never a crash.
  - **Report:** separates invalid from truncated trials and counts truncated pairs. It keeps gate evidence from
    truncated trials and shows a governed trial without gate evidence as missing. It refuses a receipts file that
    lacks any preregistered chain.
  - **Arm hash:** a governed arm's hash covers its curator policy, and `load_arm` refuses a policy that does not
    match its pin.
  - **Not done here, and tracked for the paid runs:** the image carries wiki-studio 0.4.1 only, so the governed
    arms cannot run in it until it gains wiki-studio 0.10.0 for memkernel's governed mode and the curator.
    Meanwhile the image's demo leaves them out and says so. The report's primary endpoint still fixes the
    treatment as `memkernel`.

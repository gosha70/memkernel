---
feature_id: memkernel-0-16-lifecycle-corrections
spec_mode: full
status: approved
date: 2026-11-18
collaboration_mode: single
origin:
  issue: gosha70/memkernel#90
  urls:
    - https://github.com/gosha70/memkernel/issues/90
    - https://github.com/gosha70/memkernel/issues/17
    - https://github.com/gosha70/wiki-studio/blob/b99484abb13b1be9c7d1268ecfdab944a03440aa/eval/composition/design.md
  transcripts:
    - specs/memkernel-0-16-lifecycle-corrections/origin/2026-11-18-issues-90-17.md
  origin_claim: |
    #90: "Lifecycle suite: a discriminating lc-wiki task set and a governed-composition arm." The 0.5.0 lc-wiki group
    is at ceiling because the wiki carries the answer into every arm; the next measurement needs tasks the negative
    control fails (calibrated first), an obsolete decision in every chain, corrections that travel only through each
    arm's own workflow, competing pages, and a new governed-composition arm with a scripted curator and the gate's
    own records checked. #17 asks for a reproducible agent-level benchmark, including the cases with no gain.
---

# Plan: a lifecycle task set that can tell the arms apart (#90, #17)

## Approach

1. **Tasks:** the `lc-correct` group, 12 chains (#90's eight and four more) with X and Y references, competing pages and three-outcome
   checkers.
2. **Runner:** per-arm correction events; `shared_artifact` limited to the exposure state.
3. **Arm:** `memkernel_governed` with the scripted and oracle curators and the gate-record check.
4. **Report:** a per-group token table.
5. **Then, with the owner's approval:** calibration, preregistration, budget, the measured run.

## Risks

- Calibration may drop chains (if `bare` guesses Y); the set is small by design, so a dropped chain is reported, not
  replaced after the fact.
- The composition arm depends on wiki-studio's CLI and gate; it pins the version and fails closed on drift.

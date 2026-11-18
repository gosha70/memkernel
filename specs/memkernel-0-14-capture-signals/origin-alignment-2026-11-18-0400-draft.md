# Origin alignment check — memkernel-0-14-capture-signals, the draft spec

Origin: #59 Phase 2 and the slicing plan's S3 row; the owner's D8 for S2 (origin/2026-11-18-59-s3.md).

Origin claim: as in plan.md.

Working claim:
> Two extractors chosen by measured yield: owner answers (structured AskUserQuestion answers, the owner's own text
> included) and one session-outcome record (PRs, issues, edited files); per-extractor caps; captured records out of
> the promotion candidates.

Mismatches:
  - partial, deliberate, proposed for the owner: the S3 row lists commits, owner turns, supersede suggestions and
    canonical hashing. The spec leaves out commits (git holds them; 1,045 would crowd the store) and free-form owner
    turns (no structure to key or quote), and proposes supersede suggestions and canonical hashing as their own
    slice (store features, not extractors). Each is stated under Constraints, for the owner to accept or reject.

Verdict: aligned
Confidence: medium

## Re-check after D5 and D7 (2026-11-18)

Origin line checked: the owner's decisions on D5 and D7 (origin file, last section). D5 now keeps a session's last
30 owner answers, from the per-session table; D7 (proposed) limits one recall result to 3 captured records per
origin session. The narrowing of the S3 row noted above still stands for the owner.

Verdict: aligned
Confidence: medium

## Re-check after the review of #142 (2026-11-18)

Origin lines checked: #147 (the S3 issue) and the review the owner passed on (origin file, last two sections). D3
(`episode`) and D6 (2 answers among the candidates) keep answers available past a week; outcomes read GitHub's MCP
tools as well as `gh`; constants and multi-select are specified. The S3 issue now exists, so the spec and #147
agree on scope: commits and free-form turns out, supersede suggestions and canonical hashing as S4. The review
recommends accepting that narrowing; it is no longer a mismatch with the issue the build closes.

Verdict: aligned
Confidence: high

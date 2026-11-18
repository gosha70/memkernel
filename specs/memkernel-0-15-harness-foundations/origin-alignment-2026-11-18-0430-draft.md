# Origin alignment check — memkernel-0-15-harness-foundations, the draft spec

Origin: gosha70/memkernel#119 (origin/2026-11-18-issue-119.md).

Origin claim: as in plan.md.

Working claim:
> A design and plan before coding, covering the three areas together: a scope field with agent and task views
> (Part 1) and an abstention reason; correlation ids and receipts in the recall log (Parts 2 and 3); a context-diff
> tool over receipts (Part 2); the count grouped by run and agent (Part 3). No new tool, store or dependency; three
> slices; compatibility by defaults.

Mismatches:
  - none. #119 leaves the architecture, the number of PRs and the telemetry framework open; the spec proposes them
    as D1–D6 for the owner. Its "reproducible evaluations against simpler approaches" is assigned to the lifecycle
    suite (#90, #17) rather than a new runner, stated in FR-006.

Verdict: aligned
Confidence: high

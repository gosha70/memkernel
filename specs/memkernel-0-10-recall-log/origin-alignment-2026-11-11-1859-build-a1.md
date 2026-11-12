# Origin alignment check — memkernel-0-10-recall-log, build amendment A1

Origin: gosha70/memkernel#120 (origin/2026-11-11-issue-120.md), with the counting rule from #112.

Origin claim: as in origin-alignment-2026-11-11-1300-draft.md.

Working claim:
> As approved, with A1: hook blocks log the memories they show (one record per block, the ref_ids found in the
> returned text), because a normal session start shows memories without calling recall.

Mismatches:
  - none against the origin. #112's rule asks "whether a recall returned that memory in the session before the
    failure"; memories the session-start hook injects reach the session the same way, and #120's acceptance
    ("every recall leaves one record") is kept for recall calls.

Verdict: aligned
Confidence: high

# Origin alignment check — memkernel-0-10-decision-revalidation, the draft with the dedup and hint clarifications

Origin: gosha70/memkernel#123 (origin/2026-11-13-issue-123.md).

Origin claim: as in plan.md.

Working claim:
> FR-001–FR-006: a source_hash recorded at retain for decisions with a readable source under the project root;
> revalidate flags decisions missing/changed (missing only without a hash); recall returns flagged decisions and
> keeps hiding flagged code; additive needs_review and review_reason on every recall result; the startup list per
> D1; docs.

Mismatches:
  - none. D2 puts the new fields on every result, not only decisions: #123 asks for an additive field on recall
    results, and the same field for code keeps one result shape.

Verdict: aligned
Confidence: high

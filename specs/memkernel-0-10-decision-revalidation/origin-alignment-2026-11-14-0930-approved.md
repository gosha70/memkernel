# Origin alignment check — memkernel-0-10-decision-revalidation, approved

Origin: gosha70/memkernel#123 (origin/2026-11-13-issue-123.md).

Origin claim: as in plan.md.

Working claim:
> The owner accepted D1–D4 on 2026-11-14 with two clarifications: the startup hint is type-aware (D1, FR-005), and
> a hash is computed only for the source of a newly created record, a dedup hit keeping the existing record's
> source and source_hash (D3, FR-001), with tests for cross-source, same-source and legacy dedup hits (SC-3).

Mismatches:
  - none. The clarifications keep a decision's hash bound to the file the record actually cites.

Verdict: aligned
Confidence: high

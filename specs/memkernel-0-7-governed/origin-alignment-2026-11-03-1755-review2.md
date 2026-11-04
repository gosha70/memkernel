# Origin alignment check — memkernel-0-7-governed, after the second review

Origin: as in the previous record, plus specs/memkernel-0-7-governed/origin/2026-11-03-review-2.md.

Origin claim:
> As before; the second review: auto must stay unchanged (gated/ungated, the strict preflight only in governed), a deadline that ends all work and locks, an unknown remaining on an uncertain outcome, and synchronized in-memory ledger reads.

Working claim:
> mode reports gated/ungated, configured_mode the setting; the governed preflight applies only when configured_mode is governed, so auto with a managed wiki behaves as today. findings and the preflight run in a spawned child terminated at 2 seconds; the on-disk ledger snapshot takes no lock (atomic saves), the in-memory one a non-blocking process-local lock that run() also holds. remaining is null when uncertain_outcome is set.

Mismatches:
  - none against the origin; the decisions await the owner.

Verdict: aligned
Confidence: medium

# Origin alignment check — fix-139-cross-process-recall

Origin: gosha70/memkernel#139 (origin/2026-11-18-issue-139.md).

Origin claim: as in plan.md.

Working claim:
> A count check before relevance recall; on a difference, refresh the dense index (a no-op delete) and rebuild
> BM25; own writes keep the count; a real second process in the test.

Mismatches:
  - none.

Verdict: aligned
Confidence: high

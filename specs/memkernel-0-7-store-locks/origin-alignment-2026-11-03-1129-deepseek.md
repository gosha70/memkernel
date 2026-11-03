# Origin alignment check — memkernel-0-7-store-locks, after DeepSeek on the re-entry amendment

Origin: as in the previous record.

Origin claim:
> The owner, 2026-11-03: "#87: add that locks aren't re-entrant and a nested take of the same name in one process raises; optionally log long waits."

Working claim:
> As the previous record, plus DeepSeek's wording fixes: the failure mode if chromadb stopped merging keys, no caller using required=True, and the persistent-client test asserting shared data first.

Mismatches:
  - none.

Verdict: aligned
Confidence: high

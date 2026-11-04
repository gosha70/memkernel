# Origin alignment check — memkernel-0-7-governed, after the fourth review

Origin: as in the previous record, plus specs/memkernel-0-7-governed/origin/2026-11-03-review-4.md.

Origin claim:
> As before; the fourth review: no race with the first import, the in-memory snapshot inside the bound, a reserved post-kill reap.

Working claim:
> The disk snapshot takes run()'s lock file (created if missing in an existing ledger directory) with a non-blocking shared flock; no ledger directory means zero counts, the directory check being the linearization point. The in-memory copy checks the deadline every 100 entries. terminate then join 0.3 s, kill then join 0.2 s: at most 2.5 s in all.

Mismatches:
  - none against the origin; the decisions await the owner.

Verdict: aligned
Confidence: medium

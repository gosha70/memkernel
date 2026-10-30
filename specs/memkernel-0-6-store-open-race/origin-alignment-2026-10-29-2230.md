# Origin alignment check — memkernel-0-6-store-open-race, SC-1 marker order

Origin: as in the previous record, plus specs/memkernel-0-6-store-open-race/origin/2026-10-29-sc-1-order.md.

Origin claim:
> (2026-10-29) "in SC-1 the helper writes the marker before releasing the lock"; "fixes the store-open-race SC-1 sentence (marker written before the lock is released)".

Working claim:
> SC-1 now says the helper takes the lock, writes the marker and then releases it, as #72's test does.

Mismatches:
  - none. One sentence of SC-1 changes to match the owner's instruction and the merged test.

Verdict: aligned
Confidence: high

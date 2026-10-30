# Origin alignment check — memkernel-0-6-compaction-hooks, FR-011 checkpoint selection (review of #73)

Origin: as in the previous records, plus specs/memkernel-0-6-compaction-hooks/origin/2026-10-29-review-73.md.

Origin claim:
> (2026-10-29) "latest checkpoint by time over all live checkpoints with recall's liveness rules, code-chunk and document-part records excluded, newest first with ref_id ties, used by startup, compact and on_post_compact, only the shown one touched; name MemoryService.checkpoints_newest_first() and add it to memory-tiers.md's API table".

Working claim:
> FR-011 defines the latest checkpoint as the newest by time over every live checkpoint (recall's rules, the service's settings), without code-chunk and document-part records, ties by ref_id, from MemoryService.checkpoints_newest_first(); the startup block, the compact block and on_post_compact use it and touch only the checkpoint shown; memory-tiers.md's API table and the CHANGELOG follow. FR-005 is qualified accordingly; SC-9 lists the tests.

Mismatches:
  - none. Every point of the owner's go is a clause of FR-011 or SC-9.

Verdict: aligned
Confidence: high

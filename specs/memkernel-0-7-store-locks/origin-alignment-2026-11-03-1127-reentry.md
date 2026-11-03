# Origin alignment check — memkernel-0-7-store-locks, after the owner's re-entry amendment

Origin: as in the previous record, plus specs/memkernel-0-7-store-locks/origin/2026-11-03-reentry.md.

Origin claim:
> The owner, 2026-11-03: "#87: add that locks aren't re-entrant and a nested take of the same name in one process raises; optionally log long waits."

Working claim:
> L2 adds LockReentryError for a nested take of the same name on the same store in one process (with and without fcntl) and one info line after LOCK_WAIT_LOG_SECONDS of waiting; SC-1a tests both. L4's README note no longer names a #80 operation requiring a lock.

Mismatches:
  - none.

Verdict: aligned
Confidence: high

# Origin alignment check — memkernel-0-7-store-locks, after the owner's decisions on #88

Origin: as in the previous record, plus specs/memkernel-0-7-store-locks/origin/2026-11-03-build-review.md.

Origin claim:
> The owner, 2026-11-03: "keep per-thread re-entry detection, and update the store-locks spec sentence to 'a thread'. For the injected client, refuse only when MEMKERNEL_CHROMA_PERSIST_PATH was explicitly set (env or explicit setting), not the default."

Working claim:
> L2: re-entry is detected per thread; another thread of the process waits. L1: an injected persistent client is refused only when its directory differs from an explicitly set, non-empty chroma_persist_path; with the default it is allowed and keyed by its own directory. The code and tests match.

Mismatches:
  - none.

Verdict: aligned
Confidence: high

# Origin alignment check — memkernel-0-7-store-locks

Origin: specs/memkernel-0-7-store-locks/origin/2026-11-03-split.md, gosha70/memkernel#80.

Origin claim:
> The owner, 2026-11-03: "split S8." On Windows: "If it only repeats work or leaves something the next import repairs, degrade like #69 (no lock, one logged warning, README note) instead of refusing. If it can leave identity tags permanently wrong, keep the refusal."

Working claim:
> A prerequisite spec for #80: store-keyed lock identity (persistent from the client's own directory, tenant, database and collection, with an injected-client check; in memory process-wide); VectorStorePort.exclusive and merge_tags; update_metadata refusing tags, with both current tag writers moved to merge_tags; on non-POSIX, required=True raises LockUnavailableError and required=False degrades like #69 with one warning. No wiki logic.

Mismatches:
  - none. The generic part degrades like #69 as the owner's rule asks; the refusal for wiki identity is #80's decision, in its spec.

Verdict: aligned
Confidence: high

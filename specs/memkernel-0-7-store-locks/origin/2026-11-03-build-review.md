# Origin note: the owner's decisions on build PR #88 (2026-11-03)

The owner, in their own message, quoted:

> On #88: keep per-thread re-entry detection, and update the store-locks spec sentence to "a thread". For the
> injected client, refuse only when MEMKERNEL_CHROMA_PERSIST_PATH was explicitly set (env or explicit setting),
> not the default; amend the spec sentence and drop the CHANGELOG break. One commit (no force-push); once CI is
> green, go: merge #88 (merge commit), then build #84.

Applied: L2 says "a thread" and a per-thread registry; L1 and SC-1 refuse an injected persistent client only
against an explicitly set, non-empty `chroma_persist_path` (pydantic's `model_fields_set`, which counts the
environment).

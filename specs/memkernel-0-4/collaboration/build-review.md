---
feature_id: memkernel-0-4
date: 2026-10-13
status: final
phase: build
mode: review
subject_provider: claude
peer_provider: deepseek
peer_profile: deepseek
runner_fingerprint: ae8dc147cf1264834bab35d116b6ab96b06618f438763cde3a90621d78036dba
verdict: PASS
blocking_findings_open: 0
target_ref: feature/memkernel-0-4
rounds_completed: 2
attempt_count: 1
bypass: false
---

# Peer Review: memkernel-0-4 — Build Phase

**Reviewer**: deepseek
**Scope**: both
**Rounds**: 2
**Verdict**: PASS

## Summary

The Round 1 fixes are largely sound: the compensation path now deletes the canonical first (so a mid-compensation store failure leaves hidden orphans rather than a live half-written snapshot), `chunk_refs` is used as a completion marker to rebuild partial indexes, and `find_by_hash` correctly excludes superseded records. However, the new `_supersede_other_snapshots` and `_index_missing_chunks` paths introduce a few correctness gaps around ordering, the `supersedes` link semantics, and the interaction between the dedup-refresh branch and the compensation branch.

## Findings

- [warning] f-bde7b2d6: The guard `if canonical is not None and canonical.supersedes not in other_ids` only rewrites `supersedes` when the current link is *not* one of the snapshots being replaced. On a fresh retain where `extra.supersedes` was set by the caller to a ref that is *also* in `others` (e.g. caller passes `supersedes=old` and `old` is a live canonical for the same source), the link is left pointing at `old` even though `newest` may be a different, newer snapshot. The test only covers the half-written stale-link case, not the caller-supplied-link case. (src/memkernel/core/services.py)
- [warning] f-cd845893: The completion marker is `canonical.chunk_refs` (a list). An empty list is falsy, so a canonical that legitimately has zero chunks (e.g. `_chunker is None` was true at first retain, or content chunked to nothing) will be re-chunked on every subsequent dedup hit. If `_chunker` is later set, this silently changes the record's chunk set; if it stays `None`, the early return masks it, but the semantics of "no chunks" vs "chunks not yet written" are conflated. (src/memkernel/core/services.py)
- [warning] f-70fb0c29: The refresh unconditionally rewrites `timestamp` on owned chunks to `datetime.now(UTC)`. If any downstream logic (ordering, recency ranking, `_live_code_canonicals` max-by-timestamp, or the `supersedes` newest-selection in `_supersede_other_snapshots`) relies on chunk timestamps reflecting the original write, this silently reorders history. Round 1 flagged this as `f-efe508a8` and the builder marked it not-applicable, but the diff still rewrites the timestamp rather than only `session_id`/`checkpoint`. (src/memkernel/core/services.py)
- [warning] f-34977bc1: The docstring claims "an interruption between the two steps leaves a state a retry completes rather than one with two live snapshots." But `_mark_superseded` is called in a loop over `others`; if it raises on the second `old`, the first is marked and the second is not, and the subsequent delete loop never runs. The next retain's `_supersede_other_snapshots` will re-mark the first (idempotent) and mark the second, so convergence holds — but only if `_mark_superseded` is truly idempotent and does not short-circuit on an already-marked target in a way that skips the chunk propagation. Verify `_mark_superseded` re-propagates to owned chunks on a second call. (src/memkernel/core/services.py)
- [note] f-8b626cb3: The partial-chunk cleanup iterates `self._owned_chunks(ref_id)` and deletes each. If `list_all` paginates or has a default limit, a canonical with more chunks than the page size would leave orphans that the subsequent `_index_code_chunks` would then collide with (same `{ref}-chunk-N` ids) — likely overwriting, but worth confirming the store's `upsert` semantics for chunk ids are idempotent. (src/memkernel/core/services.py)
- [note] f-c846ea96: Both tests hand-roll a metadata dict via `store.upsert` and duplicate the production metadata shape (project_id, session_id, timestamp, type, source, hash, token_count). This is the same brittleness flagged in Round 1 (`f-6b10000c`) for a different test; the fix only addressed the `compute_content_hash` import, not the metadata duplication. (tests/unit/test_code_supersession.py)
- [note] f-9059b731: Round 1 noted (`f-ccd8af5c`) that any truthy value is treated as superseded. The builder marked it not-applicable on the grounds that empty string is the "no marker" encoding. That is consistent with `_memory_from_chroma` loading empty string as `None`, but the adapter now has two places (`find_by_hash` and `_memory_from_chroma`) encoding the same invariant differently (truthiness vs. explicit `is None`). A future writer that sets `superseded_by` to a non-empty sentinel would be treated as superseded here but as live by `_memory_from_chroma` if the sentinel is not a string. (src/memkernel/storage/chroma.py)

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
rounds_completed: 1
attempt_count: 1
bypass: false
---

# Peer Review: memkernel-0-4 — Build Phase

**Reviewer**: deepseek
**Scope**: both
**Rounds**: 1
**Verdict**: PASS

## Summary

The changes address three correctness issues: superseded-record cleanup on retry, propagation of merged importance/tags to owned chunks during dedup refresh, and filtering `needs_review` health counts to live records only. The logic is generally sound and well-tested, but I found a few correctness concerns around the `_code_records` refactor, the `_refresh_owned_chunks` tag comparison, and the `marked_before` cleanup path.

## Findings

- [warning] f-65099f95: `_code_records` now returns all `code` records for a source, and `_live_code_canonicals` filters on `superseded_by is None`. But `_code_records` is also used in `_supersede_old_code_snapshots` to compute `referenced` (the set of chunk refs). If a chunk record itself has `superseded_by` set (e.g., a chunk was individually superseded), it still contributes to `referenced`, which is correct for chunk detection. However, the `canonicals` list now includes records whose `superseded_by` points to a *different* ref than `ref_id` (i.e., already superseded by an unrelated snapshot). Those are excluded from `others` (correct) but also from `marked_before` (correct), so they are silently skipped — this is fine, but the naming `canonicals` is misleading since it includes superseded records. Consider renaming to `non_chunk_records` for clarity. (src/memkernel/core/services.py)
- [warning] f-cc58d174: The comparison `",".join(chunk.tags) != tags` assumes `chunk.tags` is already deduplicated and ordered identically to `canonical.tags`. If a chunk's tags were stored in a different order (e.g., `["code_chunk", "a"]`), the join would differ from `tags` even though the sets are equal, causing an unnecessary update. More importantly, if `chunk.tags` contains duplicates, the join would not match `tags` (which is deduplicated via `dict.fromkeys`), triggering a spurious update — harmless but wasteful. Conversely, if the canonical's tags are reordered but semantically identical, chunks get rewritten unnecessarily. (src/memkernel/core/services.py)
- [warning] f-661a595f: When `others` is empty but `marked_before` is non-empty, the code skips the `supersedes` provenance update (guarded by `if others and ...`). This is correct — there is no new snapshot to point at. However, `_delete_owned_chunks(old)` is called for `marked_before` records, which deletes chunks of snapshots already marked as superseded by `ref_id`. If `ref_id` itself was deleted or is not the actual current canonical (e.g., a stale retry), this could delete chunks belonging to a snapshot that is legitimately superseded by a *different* newer snapshot. The guard `m.superseded_by == ref_id` mitigates this, but only if `ref_id` is still the live canonical. Consider verifying `ref_id` is not itself superseded before performing cleanup. (src/memkernel/core/services.py)
- [note] f-84e2fb03: `if canonical is None: return` silently skips chunk refresh when the canonical is missing. This is defensive but could mask a bug where `parent_ref` is stale. Since callers presumably just created/updated the canonical, a missing canonical indicates an inconsistent store state. Consider logging a warning or asserting, rather than silent return. (src/memkernel/core/services.py)
- [note] f-8f8a2486: The test monkeypatches `store.delete` and asserts `v1_memory.superseded_by is not None` after the failure. It does not assert that `v1`'s chunks are still present *and* that the marker was written before the failure in a way that distinguishes "marked then failed" from "failed before marking". The assertion `len(_chunks_of(store, v1)) == 2` confirms chunks remain, but the ordering of marker-write vs. chunk-delete is only implied. Consider asserting the exact `superseded_by` value equals the eventual `v2` to pin the ordering. (tests/unit/test_code_supersession.py)
- [note] f-02a9f9e8: The new condition `m.needs_review and m.superseded_by is None` correctly excludes superseded records. However, `_is_document_part(m)` and `is_chunk` checks remain. If a superseded record is also a document part, it was already excluded. No issue, but the comment says "a replaced snapshot keeps its flag as history" — this is accurate for canonicals but the filter also applies to non-chunk, non-document-part records of other types. Confirm this is intended for all memory types, not just code. (src/memkernel/core/services.py)
- [note] f-1e0321df: `_code_records` and `_live_code_canonicals` both call `list_all` with the same `where` clause. `_live_code_canonicals` now delegates to `_code_records`, which is good, but `_supersede_old_code_snapshots` calls `_code_records` directly and then re-derives `referenced` and `canonicals`. This duplicates the chunk-detection logic that `_live_code_canonicals` encapsulates. Consider extracting a helper `_code_canonicals_and_chunks(source)` returning both lists to avoid divergence. (src/memkernel/core/services.py)

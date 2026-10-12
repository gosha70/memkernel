---
feature_id: memkernel-0-3
date: 2026-10-11
status: final
phase: build
mode: review
subject_provider: claude
peer_provider: deepseek
peer_profile: deepseek
runner_fingerprint: ae8dc147cf1264834bab35d116b6ab96b06618f438763cde3a90621d78036dba
verdict: PASS
blocking_findings_open: 0
target_ref: claude/zealous-hamilton-8ehrgz
rounds_completed: 1
attempt_count: 1
bypass: false
---

# Peer Review: memkernel-0-3 — Build Phase

**Reviewer**: deepseek
**Scope**: both
**Rounds**: 1
**Verdict**: PASS

## Summary

The changes correctly address the five review fixes: filtered `count(where=...)` avoids loading records, `_document_owners` filters at the store, `retain(document)` skips chunking/embedding when already indexed, and `indexed()` provides an ids-only chunk count. The logic is sound and well-tested, but there is a subtle correctness concern around the `indexed == 0` re-index path and a potential metadata-key assumption worth flagging.

## Findings

- [warning] f-27b5789d: When `indexed == 0` the code re-chunks and re-indexes, but `_document_store.index()` is called with the same `doc_id`; if the body was already `put()` (which it was, unconditionally above), this is fine, but the comment claims "chunks were lost between put and index" — however `put()` may itself be a no-op or overwrite depending on store semantics, and there is no verification that the body content matches. If a caller retains a *different* body under the same name/source, `put()` returns a new `doc_id` (or the same?), so the `indexed(doc_id)` check is against the new doc_id and will be 0 — correct. But if `put()` is idempotent on identical content and returns the same doc_id while chunks were partially lost, re-indexing is correct. The concern is only that the branch conflates "first time" and "lost chunks" without distinguishing; behavior is acceptable but the invariant relies on `put()` returning a stable doc_id for identical content. (src/memkernel/core/services.py)
- [warning] f-7dc60e40: The filter `{DOCUMENT_PART_KEY: False}` assumes every summary record has `document_part: False` explicitly set. The docstring claims "they are new in 0.3, so no legacy store lacks the key," but this is a migration assumption. If any summary was written before this change (or by another code path that sets `document_id` without `document_part`), it will be silently excluded from `_document_owners`, causing `retain()` to create a duplicate summary instead of refreshing the existing one. (src/memkernel/core/services.py)
- [note] f-dd3fe04d: `indexed()` counts records where `chunk_index >= 0`. This assumes chunk records always carry a non-negative `chunk_index` and that no other record type under the same `document_id` has a `chunk_index`. If the body record or summary ever gains a `chunk_index` field, the count would be wrong. The test `test_owner_lookup_is_filtered_at_the_store_and_never_loads_chunks` implicitly validates the current invariant but does not guard against future drift. (src/memkernel/storage/documents.py)
- [note] f-aa719861: `self._collection.get(where=where, include=[])` still materializes the full id list in memory before `len()`. For very large filtered sets this is O(n) memory. Chroma does not expose a native filtered count, so this is a reasonable workaround, but worth noting for scale. (src/memkernel/storage/chroma.py)
- [note] f-ea474143: The assertion `store.count(where={"document_id": summary.document_id}) == chunk_count + 3` hard-codes the expected record count (body + chunks + 2 summaries). This is brittle if the body record is ever excluded from the count or if summary records change. It does correctly validate the new-name path, but the magic `+3` obscures intent. (tests/unit/test_documents.py)
- [note] f-9bad2eef: Changing `count()` to `count(where=None)` is a breaking change to the Protocol. Any external adapter implementing `VectorStorePort` must be updated. Within this repo only `ChromaVectorStore` implements it, so it is fine, but the port change should be called out in the changelog/migration notes. (src/memkernel/core/ports.py)

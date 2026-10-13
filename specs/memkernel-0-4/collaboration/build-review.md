---
feature_id: memkernel-0-4
date: 2026-10-12
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

The change implements sourced-code identity, owner-specific chunk records, and durable `superseded_by` markers for the memkernel-0.4 US1 slice. The core logic is well-structured and the test coverage is thorough, but there are a few correctness concerns around the `_live_code_canonicals` filter, the `find_by_hash` chunk-skip semantics, and the `_delete_owned_chunks` legacy path that warrant attention before merge.

## Findings

- [warning] f-806da7e7: The `referenced` set is built from `chunk_refs` of every record returned by `list_all(where, include_content=False)`, but `chunk_refs` is stored as a comma-joined string in metadata and parsed into a list by the adapter. If any record has an empty/None `chunk_refs`, the comprehension `for ref in m.chunk_refs` is safe, but the filter `not _is_code_chunk(m, referenced)` will treat a legacy canonical whose `chunk_refs` points at itself (or a self-referential cycle) as a chunk and silently drop it from the live set, causing a new retain to skip supersession of that canonical. Add a guard that excludes `m.ref_id` from `referenced` when computing the chunk test, or assert `m.ref_id not in referenced` before treating it as a chunk. (src/memkernel/core/services.py)
- [warning] f-0fb3601c: The loop returns the first non-chunk match, but `metadatas` and `ids`/`documents` are parallel lists only if Chroma returns them in the same order. The code indexes `_memory_from_chroma(ids, documents, metadatas, index)` using the metadata index, which is correct only if all three lists are aligned. Chroma does guarantee alignment, but the previous code returned index 0 unconditionally; the new code should defensively verify `len(ids) == len(metadatas) == len(documents)` before indexing, or at minimum assert it, since a mismatch would silently return the wrong record. (src/memkernel/storage/chroma.py)
- [warning] f-aa77b26e: The legacy cleanup calls `self._vector_store.list_all(include_content=False)` to find other referrers, then deletes any legacy chunk not referenced elsewhere. This is O(N) over the whole store per forget/supersession and, more importantly, it does not exclude the canonical being deleted from the "others" set correctly: `if m.ref_id != canonical.ref_id` excludes the canonical, but if the canonical's own `chunk_refs` still lists the legacy chunk (which it does, since we're iterating `canonical.chunk_refs`), the chunk is only deleted when no *other* record references it — which is the intent. However, if two canonicals share a legacy chunk and one is superseded (not forgotten), the superseded canonical's `chunk_refs` still lists the shared chunk, so the chunk is retained even though the superseded canonical is hidden. This is arguably correct (the chunk may still be referenced by the live canonical), but the superseded canonical's `chunk_refs` should be cleared to avoid stale references. Consider clearing `chunk_refs` on the superseded canonical after deleting its owned chunks. (src/memkernel/core/services.py)
- [warning] f-32f8cb31: `old_canonicals = self._live_code_canonicals(source) if source else []` is computed after the dedup check, which is correct, but the dedup check uses `find_by_hash(..., source=source or None)`. When `source` is empty string, `source or None` passes `None`, so `find_by_hash` searches across all sources for a code record with the same hash. This means an unsourced retain can dedup against a sourced record, which contradicts the "unsourced code keeps global dedup" test but may be unintended for sourced records. Verify that an unsourced retain should match a sourced record of the same content; if not, pass `source=""` explicitly and have the adapter treat empty string as a distinct filter. (src/memkernel/core/services.py)
- [warning] f-24af16a6: `_mark_superseded` returns early if `self._vector_store.get_by_id(target_ref) is None`, silently skipping the marker when the target is missing. This is defensive but means a caller passing a stale `supersedes` ref gets no feedback. More importantly, in `_retain_single`, `if extra.supersedes: self._mark_superseded(extra.supersedes, ref_id)` is called after `_write_record`, so the new record exists; but if `extra.supersedes` points at a record that was already deleted, the marker is silently dropped and the new record's `supersedes` field still points at a dead ref. Consider logging a warning when the target is missing. (src/memkernel/core/services.py)
- [note] f-9cfa5eb7: The `owners` dict caches `get_by_id` results per parent_ref, but if the same parent_ref appears in multiple results and the first lookup returns None (owner deleted), subsequent chunks of that owner are correctly dropped. However, the cache is keyed only by `parent_ref` and does not account for the possibility that the owner was superseded *during* the same recall call (it can't be, since recall is read-only). This is fine, but the `owners` dict is unbounded per call; for a large result set with many distinct owners this is O(distinct owners) extra `get_by_id` calls. Acceptable for now, but note it. (src/memkernel/core/services.py)
- [note] f-2c0ff349: `zip(chunks, embeddings, strict=True)` will raise `ValueError` if the embedding provider returns a different number of embeddings than chunks. This is a hard failure inside `retain`, which is arguably correct (fail loudly), but the error message will be a generic zip mismatch. Consider wrapping with a clearer error or asserting `len(embeddings) == len(chunks)` with a descriptive message. (src/memkernel/core/services.py)
- [note] f-84568637: The test uses `store.update_metadata(first, {"superseded_by": ""})` to simulate a missing marker, but the adapter's `_memory_from_chroma` treats empty string as falsy (`if meta.get(SUPERSEDED_BY_KEY) else None`), so this correctly yields `None`. However, the test then calls `store.update_metadata(second, {"supersedes": ""})` to clear the supersedes link, which is also treated as falsy. This works but relies on the adapter's falsy-string handling; a future change to store `None` explicitly would break the test. Consider using a helper that deletes the key or sets it to `None` explicitly. (tests/unit/test_code_supersession.py)
- [note] f-829f0c48: The port signature changed from `find_by_hash(content_hash, memory_type)` to `find_by_hash(content_hash, memory_type, source=None)`. This is a breaking change for any external implementer of `VectorStorePort`. Since this is a Protocol, existing implementations that don't accept `source` will fail at runtime when called with `source=`. Consider whether this warrants a version bump or a default-argument compatibility shim. (src/memkernel/core/ports.py)
- [note] f-2e4dfd63: The README describes `project_root` as "Directory that relative `source` paths of `code` memories resolve under; nothing outside it is ever read." However, the diff does not show any code that actually resolves `source` paths against `project_root` or enforces the "nothing outside it is ever read" constraint. This appears to be a documentation-ahead-of-implementation issue for US1 (the setting is added but not yet consumed). Verify that a later task in the bundle implements the resolution and sandboxing, or remove the claim until implemented. (README.md)

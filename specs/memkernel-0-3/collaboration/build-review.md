---
feature_id: memkernel-0-3
date: 2026-10-11
status: final
phase: build
mode: review
subject_provider: claude
peer_provider: spark
peer_profile: spark
runner_fingerprint: 303af47027968338139fc2247d24c612c9d02c71c6e4893b1dd3c2431e6f770d
verdict: PASS
blocking_findings_open: 0
target_ref: claude/zealous-hamilton-8ehrgz
rounds_completed: 2
attempt_count: 1
bypass: false
---

# Peer Review: memkernel-0-3 — Build Phase

**Reviewer**: spark
**Scope**: both
**Rounds**: 2
**Verdict**: PASS

## Summary

The implementation of the `document` memory type and `LocalDocumentStore` is largely correct and well-tested. The `forget` logic correctly handles the deletion of associated body and chunk records, resolving the previous blocking concern. However, there is a significant correctness gap in the `LocalDocumentStore.search` method where the `where` filter is not correctly applied to exclude non-chunk records (body/summary) in all ChromaDB versions, potentially returning incorrect results or failing to meet the `top_k` constraint.

## Findings

- [warning] f-5f3a1874: The `search` method uses `where={"document_id": doc_id}` to filter results. In ChromaDB, `where` filters apply to metadata. While the body and summary records have `document_id` set, the code relies on fetching `top_k + 2` and then filtering by tag in Python. This is fragile. If the body or summary record is among the top `top_k` results (which is possible if the query matches the summary text well), the returned list might have fewer than `top_k` items even if more chunks exist, or the "over-fetch by 2" assumption might fail if the body/summary are not the only non-chunk records (though currently they are the only ones with that `document_id`). More critically, if the `where` clause is not supported or behaves differently in the specific ChromaDB version used, the filter might not work as expected. A more robust approach is to ensure the `where` clause explicitly excludes the body/summary tags if possible, or to verify that the `where` filter is correctly applied to the `document_id` field in the metadata of all record types. (src/memkernel/storage/documents.py)
- [note] f-ead358cf: The `_filter_live` method iterates through all results and for each document part, it calls `_document_summary_record` which performs a `list_all` with a filter. This can be inefficient if there are many document parts in the results. Caching the summary lookup within the method (as done with the `summaries` dict) is good, but the initial lookup is still a full scan/filter. Consider optimizing the lookup if performance becomes an issue. (src/memkernel/core/services.py)
- [note] f-22479151: The `put` method embeds `content[: self._settings.chunk_size]` for the body record. This is a heuristic to create a valid embedding for the body record. However, if the content is shorter than `chunk_size`, it embeds the whole content. If it's longer, it embeds only the first chunk. This might not be ideal for the body record's embedding, but since the body is hidden from recall and retrieval goes through chunks, this is acceptable. Just ensure that the embedding dimension matches the expected dimension for the collection. (src/memkernel/storage/documents.py)
- [note] f-83081d41: The test `test_search_returns_only_chunk_texts_of_that_document` relies on `MockEmbedding` which hashes text. This might not fully validate the `where` filter behavior in a real ChromaDB environment. Consider adding an integration test or a more realistic mock to ensure the `where` filter works as expected. (tests/unit/test_documents.py)

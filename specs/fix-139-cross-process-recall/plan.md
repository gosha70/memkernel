---
feature_id: fix-139-cross-process-recall
spec_mode: none
status: draft
date: 2026-11-18
collaboration_mode: single
origin:
  issue: gosha70/memkernel#139
  urls:
    - https://github.com/gosha70/memkernel/issues/139
  transcripts:
    - specs/fix-139-cross-process-recall/origin/2026-11-18-issue-139.md
  origin_claim: |
    "A running server's recall misses records that other processes wrote to its store." Before a relevance recall,
    compare the store's record count with the count this process last saw; when they differ, refresh the dense
    index and rebuild BM25. One count per recall otherwise; a real second process in the test.
---

# Plan: a running server's recall sees other processes' writes (#139)

A bug fix (spec_mode none): no spec, this plan only.

## Change
- `VectorStorePort.refresh()`; `ChromaVectorStore.refresh()` deletes an id that cannot exist, which makes chromadb
  1.5 reload this process's dense index (measured: about 5 ms).
- `MemoryService` keeps `_seen_count`: set by `rebuild_sparse_index()`, plus one per `_write_record`, minus one per
  successful `_delete_record`. A relevance `recall` first compares it with `count()`; on a difference it calls
  `refresh()` and `rebuild_sparse_index()`.
- `recall(order="newest")` and the metadata reads are unchanged (they already see other processes' writes).

## Tests
- A real second process writes after the service started; recall finds the record (fails on `main`).
- Own writes and deletes never trigger a refresh; another process's writes trigger exactly one.

## Limits (stated in the issue and the code)
- An addition and a deletion by others between two recalls leave the count equal and are not detected.
- Writes that bypass `_write_record` in this process (the document store's bodies and chunks) make the count
  differ, which costs one unnecessary refresh and BM25 rebuild at the next recall, not a wrong result.
- The refresh relies on chromadb's current behaviour; the cross-process test fails if an upgrade changes it.

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

The implementation of the `ask` feature (US2) is structurally sound, correctly wires the `LocalReasoner` into the service and MCP layers, and handles edge cases like missing documents and invalid modes appropriately. The primary concern is a potential performance bottleneck in `LocalReasoner` where the embedding model is called for every `ask` request, which could be significant for large documents or high-frequency usage.

## Findings

- [warning] f-d4d8b821: The `_dense_rank` method calls `self._embedding.embed([question, *chunks])` on every `ask` invocation. For large documents with many chunks, this results in a full re-embedding of the document content for every question, which is computationally expensive and defeats the purpose of having a pre-indexed vector store. The `LocalReasoner` should ideally leverage the existing vector store or a cached embedding of the document body if available, or at least document this performance characteristic clearly. (src/memkernel/retrieval/reasoner.py)
- [note] f-fd700f90: The `_sparse_rank` method rebuilds a `BM25Index` from scratch on every `ask` call. While correct, this is inefficient for large documents. Consider caching the BM25 index per document ID or using the existing sparse index if the document chunks are already indexed in the main store. (src/memkernel/retrieval/reasoner.py)
- [note] f-1bd5d69d: The `ask` method in `MemoryService` resolves the document body by calling `self._document_store.get(memory.document_id)`. If the document store is not configured (`self._document_store is None`), it falls back to `memory.content` (the summary). This is a reasonable fallback, but it might be surprising if a user expects the full body to be available. Consider logging a warning when falling back to the summary for a document type, which is already done, but ensure this behavior is documented in the API docs. (src/memkernel/core/services.py)
- [note] f-8e4b1bf9: The test `test_ask_without_any_term_overlap_still_returns_dense_neighbours` uses a mock embedding. In a real scenario, if the question has no term overlap with the document, the BM25 score will be 0, and the dense ranking will determine the result. The test correctly verifies that dense neighbours are returned, but it might be worth adding a test with a real embedding model to ensure the RRF fusion behaves as expected when one signal is weak. (tests/unit/test_reasoner.py)

---
spec_mode: lightweight
feature_id: memkernel-0-6-store-open-race
risk_category: bugfix
justification: "One adapter (storage/chroma.py) and its tests, plus a CHANGELOG entry: fewer than three source files and no port, schema or dependency change, so a lightweight spec. It is written in full because the choice between three fixes rests on measurements that reviewers need to see."
status: draft
date: 2026-10-29
collaboration_mode: single
origin:
  issue: gosha70/memkernel#69
  urls:
    - https://github.com/gosha70/memkernel/issues/69
  transcripts:
    - specs/memkernel-0-6-store-open-race/origin/2026-10-29-issue-69.md
    - specs/memkernel-0-6-store-open-race/origin/2026-10-29-sc-1-order.md
  origin_claim: |
    Fix #69: in a project's first session the SessionStart hook and memkernel's MCP
    server open the same new ChromaDB store at once and one fails with "table
    collections already exists". The owner's go (2026-10-29): a spec in its own
    specs/ feature directory that weighs options A, B and C and says which
    processes the chosen fix protects (the MCP server, all three hooks and the
    admin API open the store through build_service), with #69's three tests and a
    CHANGELOG entry in the tasks; spec-only PR for the reviewer.
---

# Plan: a store's first open no longer races (#69)

## Approach
Hold an exclusive advisory lock on a file inside the persist directory while `ChromaVectorStore.__init__` opens
its `PersistentClient` and gets or creates its collection (spec FR-001). Every memkernel process that opens a
persisted store does it through that constructor, so one change covers all of them (FR-002). Options A (retry)
and C (the hook skips a missing store) are weighed in the spec and not built.

## Files
- `src/memkernel/storage/chroma.py`: the lock around the open (FR-001, FR-003, FR-004).
- `tests/unit/test_chroma.py`: the deterministic tests (SC-1, SC-2, SC-4).
- `tests/integration/test_store_open_race.py`: the two-process stress test, marked `slow` (SC-3).
- `CHANGELOG.md`: a Fixed entry under `[Unreleased]` (FR-005).

## Measurements behind the choice (2026-10-29, chromadb 1.5.9, Python 3.13, macOS)
Two processes, started at the same instant, open one new persist directory; 60 trials each:
- **Today:** 10 of 120 opens failed, all in `chromadb.PersistentClient(...)` with `InternalError: ... table
  collections already exists`; none in `get_or_create_collection`.
- **Option A, a retry without touching chromadb's cache:** the retries failed with `AttributeError:
  'RustBindingsAPI' object has no attribute 'bindings'`, because the failed system stays cached for that path.
- **Option A, a retry after `SharedSystemClient.clear_system_cache()`:** the 2 retries succeeded and both
  processes saw one collection with both records.
- **Option B, `fcntl.flock` around the open:** 120 of 120 opens succeeded; in every trial both processes saw one
  collection with both records.

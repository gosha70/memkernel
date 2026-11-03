---
spec_mode: full
feature_id: memkernel-0-7-store-locks
risk_category: bugfix
justification: "Changes a core port (VectorStorePort gains merge_tags and exclusive; update_metadata refuses tags), the ChromaDB adapter's concurrency and lock identity, and behavior on non-POSIX platforms: a cross-cutting storage contract, so a full spec."
status: approved
date: 2026-11-03
collaboration_mode: single
origin:
  issue: gosha70/memkernel#80
  urls:
    - https://github.com/gosha70/memkernel/issues/80
  transcripts:
    - specs/memkernel-0-7-store-locks/origin/2026-11-03-split.md
    - specs/memkernel-0-7-store-locks/origin/2026-11-03-reentry.md
    - specs/memkernel-0-7-store-locks/origin/2026-11-03-approval.md
  origin_claim: |
    The owner, 2026-11-03: "split S8." S8 was the concurrency and tag-integrity
    section of the #80 spec (memkernel-0-7-wiki-scope, PR #84), added over three
    review passes: imports need cross-process atomicity, tag writes must not be
    lost, and lock identity must follow the store. Both reviewers recommended a
    prerequisite spec because it changes a port, the adapter's concurrency and
    Windows behavior.
---

# Plan: store-keyed locks and a single tag writer (prerequisite of #80)

## Why a separate spec
The #80 spec (`memkernel-0-7-wiki-scope`) needs two guarantees from the store: one wiki import at a time per
store, and tag writes that are never lost. Neither is about wikis, and both change a port and the ChromaDB
adapter, so they get their own spec, review and concurrency tests. #80's build depends on this one.

## Facts (checked 2026-11-03, on main `a1a5b32`)
- `update_metadata` fetches, merges and writes the whole metadata with no lock (`storage/chroma.py:301-320`);
  its port contract accepts any keys (`core/ports.py:52-54`).
- Two writers pass `tags` through it: the dedup refresh `MemoryService._refresh_existing`
  (`core/services.py:676-688`, a value computed from a record read before the call) and the code-chunk sync
  that copies a canonical record's tags to its chunks (`core/services.py:447-463`).
- chromadb 1.5.9 (`pyproject.toml`: `>=1.0,<2`): `collection.update(metadatas=[{"n": 2}])` kept the existing
  `tags` key, so updates merge keys natively.
- The store is chosen by `chroma_persist_path` and the collection `<prefix>_<project_id>`
  (`storage/chroma.py:165-176`); `state_dir` is a separate setting (`config.py:34-39`).
- `ChromaVectorStore(settings, client=...)` accepts any `ClientAPI` (`storage/chroma.py:160-176`).
  `client.get_settings()` gives `is_persistent` and `persist_directory`; clients expose `tenant` and `database`.
- Two `EphemeralClient()` objects are distinct but share one `_system`: a record added through one is visible
  through the other.
- Without `fcntl` the store-open lock runs unlocked and logs once at debug level (#69, `storage/chroma.py:31-65`).
- CI runs on `ubuntu-latest` only (`.github/workflows/ci.yml`).

## Files (for the build)
`src/memkernel/core/ports.py`, `src/memkernel/storage/chroma.py`, `src/memkernel/core/services.py`, tests,
README, `docs/architecture/memory-tiers.md`, CHANGELOG. Read `memory-tiers.md` and ADR-007 first (port change).

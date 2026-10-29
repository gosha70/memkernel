# Tasks: a store's first open no longer races (#69)

<!-- One `## US<n>:` group = one build phase. -->

## US1: The lock and its tests

| # | [P] | Task | File(s) | Owner | Done |
|---|-----|------|---------|-------|------|
| 1 | | Lock `.memkernel-open.lock` in the persist directory around `PersistentClient` and `get_or_create_collection`; `fcntl` only, unlocked with a debug log where it is missing; released on every path (FR-001, FR-003, FR-004) | `src/memkernel/storage/chroma.py` | build | [ ] |
| 2 | | Deterministic tests: a fake `PersistentClient` raises the injected `table … already exists` error until another process has released the lock; the store's open waits and succeeds, and fails without the lock (SC-1); another error releases the lock and propagates (SC-2) | `tests/unit/test_chroma.py` | build | [ ] |
| 3 | | Two-process stress test, marked `slow`, 60 trials: every open succeeds (SC-3), one collection, a write by one read by the other (SC-4) | `tests/integration/test_store_open_race.py` | build | [ ] |
| 4 | | CHANGELOG `[Unreleased]` Fixed entry naming #69 and the lock file (FR-005) | `CHANGELOG.md` | build | [ ] |

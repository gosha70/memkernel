# Tasks: store-keyed locks and a single tag writer (prerequisite of #80)

<!-- One `## US<n>:` group = one build phase. Build on the owner's go after the spec merges, before #80's build. -->

## US1: Store locks and the tag writer

| # | [P] | Task | File(s) | Owner | Done |
|---|-----|------|---------|-------|------|
| 1 | | Lock identity, the injected-client check, `exclusive`, `LockReentryError`, the long-wait log, `LockUnavailableError` and the non-POSIX branch (FR-001, FR-002, FR-004; read memory-tiers.md and ADR-007 first) | `src/memkernel/core/ports.py`, `src/memkernel/storage/chroma.py`, `src/memkernel/core/models.py` (`LockUnavailableError`, `LockReentryError`) | build | [ ] |
| 2 | | `update_metadata` refusing `tags`; `merge_tags`; `_refresh_existing` and the code-chunk sync moved to it (FR-003) | `src/memkernel/core/ports.py`, `src/memkernel/storage/chroma.py`, `src/memkernel/core/services.py` | build | [ ] |
| 3 | | Tests SC-1, SC-1a, SC-2 and SC-3 (SC-1 and SC-2 with real processes) | `tests/unit/test_chroma.py`, `tests/unit/test_services.py`, `tests/integration/test_store_locks.py` | build | [ ] |
| 4 | | README, memory-tiers.md, CHANGELOG (FR-005) | docs | build | [ ] |
| 5 | | Gates: fast suite green, coverage ≥ 80 percent, ruff and mypy clean (SC-4) | — | build | [ ] |

# Tasks: memkernel 0.7, Release B part 2b: withdrawal and sync state

<!-- One `## US<n>:` group = one build phase. Decisions D1-D5 confirmed 2026-10-30 (D3 changed); build on the owner's go. -->

## US1: The withdrawn marker in core

| # | [P] | Task | File(s) | Owner | Done |
|---|-----|------|---------|-------|------|
| 1 | | `withdrawn_reason` and `withdrawn_at` on `Memory`, loaded as `None` when absent (FR-001); read memory-tiers.md first | `src/memkernel/core/models.py`, `src/memkernel/storage/chroma.py` | build | [ ] |
| 2 | | One liveness predicate used by every live-record site, and dedup skipping withdrawn records (FR-002) | `src/memkernel/core/services.py`, `src/memkernel/storage/chroma.py`, `src/memkernel/wiki/sync.py` | build | [ ] |
| 3 | | `MemoryService.withdraw(ref_id, reason)`: chunks first, idempotent, refuses unknown or another project's record, never overwrites (FR-003) | `src/memkernel/core/services.py` | build | [ ] |
| 4 | | Tests: SC-5, plus `withdraw`'s refusals and idempotence | `tests/unit/test_services.py`, `tests/unit/test_chroma.py` | build | [ ] |

## US2: The ledger and the governed import's withdrawals

| # | [P] | Task | File(s) | Owner | Done |
|---|-----|------|---------|-------|------|
| 5 | | The sync ledger: per project and wiki (`wiki_id`, else the project-relative path's sha256) in `MEMKERNEL_STATE_DIR` (resolved like the persist path; README row and gitignore note), the lock held for the whole run, atomic writes, in memory for an in-memory store, rebuilt from tags when corrupt (FR-004) | `src/memkernel/wiki/ledger.py`, `src/memkernel/config.py`, README config table | build | [ ] |
| 6 | | Deletion (D3: ledger-recorded memories only), supersession (D4: successor by path, unknown successors pending and reported) and deprecation (D5: once the deprecated revision is approved) in the governed import, through the ledger; retry of pending and failed entries first (FR-005, FR-007) | `src/memkernel/wiki/sync.py` | build | [ ] |
| 7 | | `ImportReport` and `wiki_import` response keys and description (FR-006) | `src/memkernel/wiki/sync.py`, `src/memkernel/mcp/tools/wiki.py` | build | [ ] |
| 8 | | Tests against the real wiki-studio: SC-1 to SC-4 and SC-6 | `tests/integration/test_wiki_withdrawal.py` | build | [ ] |
| 9 | | memory-tiers.md, README, CHANGELOG (FR-008) | docs | build | [ ] |

# Tasks: memkernel-0-10-decision-revalidation

## US1: hash and revalidate
- [x] `source_hash` key, recorded at retain for decisions (FR-001, D3); loads empty for old records
- [x] `revalidate()` checks decisions (FR-002); flagged items carry the type
- [x] Unit tests for SC-1 (probe), SC-2 (legacy, clearing, unknown) and SC-3 (cross-source dedup, same-source dedup,
  a legacy hashless dedup hit)

## US2: recall and startup
- [x] `_filter_live` and `_newest_checkpoints()` (via `include_flagged_decisions`, default off) return flagged decisions (FR-003); `ArtifactRef` fields from both
  builders (FR-004, D2); a test for the newest-checkpoint path (SC-3c)
- [x] Startup "Needs review" list per D1, with a type-aware hint (FR-005)
- [x] Tests: recall marks, code still hidden, the startup list; a 0.9.x store fixture (SC-4)

## US3: docs and checks
- [x] README, CHANGELOG (FR-006)
- [x] #57 replay re-run (SC-3b); fast suite, ruff, mypy strict, coverage

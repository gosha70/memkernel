# Tasks: compaction hooks that do what they say (#68)

<!-- One `## US<n>:` group = one build phase. -->

## US1: Lifecycle and hook scripts

| # | [P] | Task | File(s) | Owner | Done |
|---|-----|------|---------|-------|------|
| 1 | | `on_pre_compact` retains nothing without a summary (FR-001); `capture_compact_summary` with the three tags (FR-002); `on_session_start(source)` branching and the `compact` recovery block without compact-summary checkpoints or consolidation, with the checkpoint's age line (FR-003, FR-004); `on_post_compact` and `on_session_end` unchanged (FR-005) | `src/memkernel/lifecycle.py` | build | [x] |
| 2 | | The three scripts read their stdin JSON and pass `source`, `compact_summary`, `session_id`, `trigger` through; absent or unparsable means absent, and a terminal on stdin is not read; stdout only from `session-start.py`, and only when not empty (FR-006, FR-007) | `templates/hooks/*.py` | build | [x] |
| 3 | | Tests: SC-1 to SC-6 through `MemoryLifecycle` (spies for consolidate and recall; both hook orders for SC-4); the placeholder test now asserts nothing is retained | `tests/unit/test_lifecycle_component.py` | build | [x] |
| 4 | | Tests: SC-7, each script's `main()` with the reference payloads on stdin and a test service | `tests/unit/test_hook_scripts.py` | build | [x] |

## US2: Documentation

| # | [P] | Task | File(s) | Owner | Done |
|---|-----|------|---------|-------|------|
| 5 | | README hooks table (119-121), session protocol (173-176), setup (`SessionStart` without a matcher); memory-tiers.md hooks row (FR-008) | `README.md`, `docs/architecture/memory-tiers.md` | build | [x] |
| 6 | | CHANGELOG `[Unreleased]`: Fixed D1–D3, Changed D4 and `post-compact.py`'s stdout, re-copy note (FR-009) | `CHANGELOG.md` | build | [x] |

## US3: The latest checkpoint (FR-011, from the review of #73)

| # | [P] | Task | File(s) | Owner | Done |
|---|-----|------|---------|-------|------|
| 7 | | `MemoryService.checkpoints_newest_first()` (recall's liveness with the service's settings, no code-chunk or document-part records, ties by `ref_id`, no content, no touch); the startup block, the `compact` block and `on_post_compact()` use it and touch only the checkpoint shown; memory-tiers.md; CHANGELOG Fixed; tests SC-9 (FR-011) | `src/memkernel/core/services.py`, `src/memkernel/lifecycle.py`, `docs/architecture/memory-tiers.md`, `CHANGELOG.md`, `tests/unit/test_lifecycle_component.py`, `tests/unit/test_services.py` | build | [x] |

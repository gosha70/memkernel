# Tasks: memkernel 0.7 hooks, D5–D9 of #59

<!-- One `## US<n>:` group = one build phase. H1–H4 as amended after the review of 2026-10-30; build on the owner's go. -->

## US1: D5–D8 and the agents' latest checkpoint

| # | [P] | Task | File(s) | Owner | Done |
|---|-----|------|---------|-------|------|
| 1 | | `ref_id` on every injected line and on the checkpoint's age line (FR-001) | `src/memkernel/lifecycle.py` | build | [x] |
| 2 | | Startup context by type, importance and recency (no query); compact context recalled with the checkpoint's text; no touch on injection; follow-up for a calibrated floor recorded in #59 (FR-002, H1) | `src/memkernel/lifecycle.py`, `src/memkernel/core/services.py` | build | [x] |
| 3 | | Per-section budgets under 9,000 characters (FR-003) | `src/memkernel/lifecycle.py` | build | [x] |
| 4 | | In-block de-duplication, and instructions that do not repeat the hooks (FR-004) | `src/memkernel/lifecycle.py`, `templates/claude-memory-instructions.md`, `templates/kiro/steering/memory.md` | build | [x] |
| 5 | | `recall(order="newest")`, only with `checkpoint_only=true`; docs and Kiro prompt use it for the latest checkpoint (FR-005, H2) | `src/memkernel/core/services.py`, `src/memkernel/mcp/tools/memory.py`, `README.md`, `templates/` | build | [x] |
| 6 | | Frozen copy of the 0.5 block for the arms test (FR-006, H3) | `eval/lifecycle-suite/arms/`, `tests/unit/test_lifecycle_arms.py` | build | [x] |
| 7 | | Tests SC-1 to SC-6; CHANGELOG, README, memory-tiers.md (FR-007) | tests, docs | build | [x] |

## US2: D9, SessionEnd

| # | [P] | Task | File(s) | Owner | Done |
|---|-----|------|---------|-------|------|
| 8 | | `session-end.py` `ended` line and `session-start.py` `started` line, in `MEMKERNEL_STATE_DIR`'s spool; no store and no model in session-end (FR-008, H4) | `templates/hooks/session-end.py`, `templates/hooks/session-start.py` | build | [ ] |
| 9 | | Drain at startup: the notice for an ended session with no checkpoint inside its window (FR-009) | `src/memkernel/lifecycle.py` | build | [ ] |
| 10 | | Tests SC-7; CHANGELOG and README for the new hook (FR-010) | `tests/unit/test_hook_scripts.py`, `tests/unit/test_lifecycle_component.py`, docs | build | [ ] |

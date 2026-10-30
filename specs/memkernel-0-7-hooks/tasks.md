# Tasks: memkernel 0.7 hooks, D5–D9 of #59

<!-- One `## US<n>:` group = one build phase. Build starts only after the owner confirms H1–H4. -->

## US1: D5–D8 and the agents' latest checkpoint

| # | [P] | Task | File(s) | Owner | Done |
|---|-----|------|---------|-------|------|
| 1 | | `ref_id` on every injected line and on the checkpoint's age line (FR-001) | `src/memkernel/lifecycle.py` | build | [ ] |
| 2 | | Relevance floor on dense similarity, with the default measured on `eval/run_eval.py`; `touch=False` for injection (FR-002, H1) | `src/memkernel/lifecycle.py`, `src/memkernel/retrieval/search.py`, `src/memkernel/config.py`, README config table | build | [ ] |
| 3 | | Per-section budgets under 9,000 characters (FR-003) | `src/memkernel/lifecycle.py` | build | [ ] |
| 4 | | In-block de-duplication, and instructions that do not repeat the hooks (FR-004) | `src/memkernel/lifecycle.py`, `templates/claude-memory-instructions.md`, `templates/kiro/steering/memory.md` | build | [ ] |
| 5 | | `recall(order="newest")`; docs and Kiro prompt use it for the latest checkpoint (FR-005, H2) | `src/memkernel/core/services.py`, `src/memkernel/mcp/tools/memory.py`, `README.md`, `templates/` | build | [ ] |
| 6 | | Frozen copy of the 0.5 block for the arms test (FR-006, H3) | `eval/lifecycle-suite/arms/`, `tests/unit/test_lifecycle_arms.py` | build | [ ] |
| 7 | | Tests SC-1 to SC-6; CHANGELOG, README, memory-tiers.md (FR-007) | tests, docs | build | [ ] |

## US2: D9, SessionEnd

| # | [P] | Task | File(s) | Owner | Done |
|---|-----|------|---------|-------|------|
| 8 | | `session-end.py` spool writer, no store and no model (FR-008, H4) | `templates/hooks/session-end.py` | build | [ ] |
| 9 | | Drain at startup, with the one-line notice (FR-009) | `src/memkernel/lifecycle.py` | build | [ ] |
| 10 | | Tests SC-7; CHANGELOG and README for the new hook (FR-010) | `tests/unit/test_hook_scripts.py`, `tests/unit/test_lifecycle_component.py`, docs | build | [ ] |

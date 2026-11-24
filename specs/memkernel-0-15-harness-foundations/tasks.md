# Tasks: memkernel-0-15-harness-foundations

## US1 (H1): receipts and correlation
- [x] Run, agent and task ids per call and per process (FR-002)
- [x] Receipt fields in the recall log: hashes, states, latency, size, exclusion counts (FR-003); the count grouped by run and agent (FR-006)

## US2 (H2): scope and abstention
- [x] `scope` on records, `agent`/`task` on every read path, promotion keeping scope (FR-001, SC-1); the empty-result reason in the receipt (FR-005, SC-6)

## US3 (H3): context diff
- [x] `eval/context-diff/diff.py` over a run's receipts (FR-004)

## US4: docs and checks
- [ ] README "Using memkernel from a harness" (FR-007); SC-1–SC-5

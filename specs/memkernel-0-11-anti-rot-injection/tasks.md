# Tasks: memkernel-0-11-anti-rot-injection

## US1: selector and paths
- [ ] Hook selector with the dense floor (FR-001, D1); abstention (FR-003, D4)
- [ ] Compact recovery and `on_post_compact()` use it (FR-002, D2); `on_post_compact()` applies `_distinct()` (FR-004)
- [ ] Floor value per D3; unit tests for SC-1 and SC-2

## US2: calibration
- [ ] Calibration runner over the #57 crowded store through the full hook paths, checkpoint-shaped and bare queries
  (FR-006, D5 with the 0.05 margin); record SC-3 in the spec
- [ ] #57 replay regression (SC-4)

## US3: docs and checks
- [ ] README, CHANGELOG (FR-007); fast suite, ruff, mypy strict, coverage (SC-5)

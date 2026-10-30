# Tasks: the wiring check on both import paths (#81), and spool pruning (#79 follow-up)

<!-- One `## US<n>:` group = one build phase. Build on the owner's go after the spec merges. -->

## US1: The wiring check on both paths (#81)

| # | [P] | Task | File(s) | Owner | Done |
|---|-----|------|---------|-------|------|
| 1 | | `--wiki-path` with `auto`, `governed` (mark stable through a promoted update, then approve, through the server's interpreter), `ungoverned` (stub hides wiki-studio from the server) and `both`; the report names the path(s) (FR-001) | `eval/lifecycle-suite/wiring/wiring_check.py` | build | [x] |
| 2 | | Slow test runs `both`; fast test for the stub (FR-002, SC-1 to SC-3) | `tests/unit/test_wiring_check.py` | build | [x] |

## US2: Spool pruning (#79 follow-up)

| # | [P] | Task | File(s) | Owner | Done |
|---|-----|------|---------|-------|------|
| 3 | | Remove unended sessions older than `SPOOL_UNENDED_MAX_AGE` and count them; W2's one line (FR-004) | `src/memkernel/session_spool.py`, `src/memkernel/lifecycle.py` | build | [x] |
| 4 | | Tests SC-4; README and CHANGELOG (FR-005) | `tests/unit/test_lifecycle_component.py`, `README.md`, `CHANGELOG.md` | build | [x] |

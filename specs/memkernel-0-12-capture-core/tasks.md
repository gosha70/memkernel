# Tasks: memkernel-0-12-capture-core

## US1: reader and spool
- [ ] `TranscriptReaderPort` and the Claude Code adapter (FR-004); the #120 count on the adapter, subagent files and sidechain lines included (FR-004, R7)
- [ ] Spool: `transcript_path`, `DrainResult.ended`, `reported` / `capture_missed` lines, `commit()`, age cap (FR-001)

## US2: capture
- [ ] Extractor (FR-005), redaction (FR-006), key and store (FR-003), commit after store (FR-002)
- [ ] Startup: budget and caps (FR-007, D6), misses (FR-008), report line (FR-009)
- [ ] `consolidate()` leaves captured records out (FR-010); count reports captured errors apart (FR-011)
- [ ] Count: repeats only from FR-005 failures, the command in the evidence (R8); multi-word stored errors (R9); subagent repeats apart (R10); README limits (R11); `sidechain`/`agent_id` on steps, recalls kept per thread (R12); README on duplicate captured text (R13); subagent "shown" rule (R14); recursive subagent files, agent_id fallback (R15)
- [ ] Copy `specs/memkernel-0-12-capture-core/fixtures/*.jsonl` into the test tree; tests for SC-1–SC-8

## US3: docs and checks
- [ ] `MEMKERNEL_CAPTURE` setting; README, CHANGELOG (FR-012); fast suite, ruff, mypy strict, coverage (SC-9)

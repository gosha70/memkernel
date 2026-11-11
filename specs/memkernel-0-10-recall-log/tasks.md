# Tasks: memkernel-0-10-recall-log

## US1: the recall log
- [ ] `recall_log`, `recall_log_max_bytes`, `recall_log_max_files` settings and README rows (FR-004, D3)
- [ ] `src/memkernel/recall_log.py`: append, lock, rotation, disabled and in-memory no-ops, error logged once (FR-001–FR-003)
- [ ] Call sites: MCP `recall` tool and the two lifecycle recalls (D1)
- [ ] Unit tests for SC-1 and SC-2

## US2: the counting script
- [ ] `eval/repeat-mistakes/transcripts.py`: Claude Code reader (sessions, windows, Bash results, memkernel recall calls), marked temporary (FR-006)
- [ ] `eval/repeat-mistakes/count.py`: signatures (D5), repeats, classes (D6), linking (D2), text and `--json` report (FR-005)
- [ ] Fixture and test for SC-3, including the after-the-failure recall, the two-span line, and the ambiguous pairing

## US3: docs and checks
- [ ] README "Counting repeated mistakes" section; CHANGELOG `[Unreleased]` (FR-007)
- [ ] Fast suite, ruff, mypy strict, coverage (SC-4)

# Tasks: memkernel-0-14-capture-signals

## US1: reader and extractors
- [ ] Structured `AskUserQuestion` questions and answers on `ToolStep` (FR-001)
- [ ] Owner-answer extractor (FR-002, D1–D3); session-outcome extractor (FR-003, D4)
- [ ] Per-extractor caps, owner answers keeping the last 30, up to 2 answers among the promotion candidates; the report's per-extractor counts (FR-004, FR-006)
- [ ] At most 3 captured records per origin session in one recall result (FR-008, D7)

## US2: tests, review and docs
- [ ] Fixtures cut from real transcripts; SC-1–SC-3; a false-positive review of a sample of records
- [ ] README "Capture", CHANGELOG (FR-007); fast suite, ruff, mypy strict, coverage (SC-4)

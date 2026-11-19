# Tasks: memkernel-0-14-capture-signals

## US1: reader and extractors
- [x] Structured `AskUserQuestion` questions and answers on `ToolStep` (FR-001)
- [x] Owner-answer extractor (FR-002, D1–D3); session-outcome extractor (FR-003, D4)
- [x] Per-extractor caps, owner answers keeping the last 30, up to 2 answers among the promotion candidates; the report's per-extractor counts (FR-004, FR-006)
- [x] At most 3 captured records per origin session in one recall result (FR-008, D7)

## US2: tests, review and docs
- [x] Fixtures cut from real transcripts; SC-1–SC-3; a false-positive review of a sample of records
- [x] README "Capture", CHANGELOG (FR-007); fast suite, ruff, mypy strict, coverage (SC-4)

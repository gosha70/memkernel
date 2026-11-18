# Tasks: memkernel-0-13-one-store-across-tools

## US1: several servers and one shared server
- [ ] Two stdio server subprocesses on one store (FR-001, SC-1); the #139 fix is on `main`
- [ ] Two clients on one HTTP server subprocess; host and origin checks on the HTTP transport (FR-002, SC-2)

## US2: session-start command and templates
- [ ] `memkernel session-start --format plain|cursor|antigravity [--max-chars N]` (FR-003, SC-3)
- [ ] `templates/codex/`, `templates/cursor/`, `templates/antigravity/` per D3 (FR-004, SC-4)

## US3: docs and checks
- [ ] README "One store across tools"; CHANGELOG (FR-005); fast suite, ruff, mypy strict, coverage (SC-5)

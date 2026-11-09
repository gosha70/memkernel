# Tasks: move memkernel to mcp 2.x (#95)

<!-- Build on the owner's go after the spec is approved. -->

## US1 and US2: one environment, hosts unchanged

| # | [P] | Task | File(s) | Owner | Done |
|---|-----|------|---------|-------|------|
| 1 | | Pin `mcp>=2.3,<3` (D1); relock | `pyproject.toml`, `poetry.lock` | build | [x] |
| 2 | | `MCPServer`, `run()` host/port, lifespan holder for `memory://status` (FR-001, FR-002) | `src/memkernel/mcp/server.py` | build | [x] |
| 3 | [P] | `Context` import and arity; `ValueError` reaches the client as `ToolError` (FR-008) | `src/memkernel/mcp/tools/memory.py`, `wiki.py`, `errors.py` | build | [x] |
| 4 | | In-process client in the e2e and governed-mode tests (FR-003) | `tests/e2e/test_mcp_roundtrip.py`, `tests/integration/test_wiki_governed_mode.py` | build | [x] |
| 5 | | Fast stdio and Streamable HTTP roundtrips via a launcher; one `slow` real-command stdio roundtrip (FR-004, D2) | `tests/e2e/` | build | [x] |
| 6 | | Wiring check on 2.x (FR-007) | `eval/lifecycle-suite/wiring/` | build | [x] |
| 7 | [P] | ADR-011, README, CHANGELOG, `CLAUDE.md` (FR-005, FR-006) | docs | build | [x] |
| 8 | | Gates SC-1 to SC-4 | — | build | [x] |

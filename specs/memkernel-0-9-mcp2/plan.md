---
feature_id: memkernel-0-9-mcp2
spec_mode: full
status: approved
date: 2026-11-08
collaboration_mode: single
origin:
  issue: gosha70/memkernel#95
  urls:
    - https://github.com/gosha70/memkernel/issues/95
    - https://py.sdk.modelcontextprotocol.io/v2/migration/#fastmcp-renamed-to-mcpserver
  transcripts:
    - specs/memkernel-0-9-mcp2/origin/2026-11-08-issue-95.md
  origin_claim: |
    "Evaluate moving to mcp 2.x." Done when either a branch on mcp 2.x passes the fast suite and the e2e tests,
    passes two new end-to-end tests (a stdio roundtrip against the server started as a subprocess, and a
    Streamable HTTP roundtrip with a live client against the running server), and installs memkernel[wiki] and
    wiki-studio[mcp] together in one environment; or a short record explains why memkernel stays on 1.x.
---

# Plan: move memkernel to mcp 2.x (#95)

The checked facts in `spec.md` show the move is feasible: the API changes are local to `src/memkernel/mcp/` and
the tests, the wire protocol versions are unchanged, and one environment resolves. So this takes the issue's first
"done when" branch, and the ADR records why.

## Approach

1. **Dependency** (D1): `mcp = ">=2.3,<3"` in `pyproject.toml`; `poetry lock`.
2. **Server** (`src/memkernel/mcp/server.py`): `MCPServer`; `host`/`port` passed to `run()` for
   `streamable-http` only; the lifespan stores its `MemKernelContext` in a holder the `memory://status` resource
   reads (FR-002).
3. **Tools** (`src/memkernel/mcp/tools/memory.py`, `wiki.py`): import `Context` from `mcp.server.mcpserver`;
   two type parameters.
4. **Tests**: the e2e and the governed-mode integration test use `mcp.client.Client(server)`; new transport
   tests per D2: a launcher under `tests/e2e/` for fast stdio and Streamable HTTP roundtrips (a free port for HTTP,
   bounded timeouts, the subprocess always terminated), plus one `slow` stdio roundtrip on the real `memkernel`
   command.
5. **Wiring check**: run it against 2.x; fix only if it breaks (FR-007).
6. **Docs**: ADR-011, README one-environment install, CHANGELOG, `CLAUDE.md` layout line.
7. **Gates**: ruff, mypy strict, fast suite with coverage, e2e, `poetry build`, the SC-3 dry run, SC-4 by hand.

## Risks

- 2.x behaviour differences the API diff does not show (error shapes, structured output defaults): the e2e tests'
  assertions on results are the check; any change in a tool's visible output is reported, not silently accepted.
- mypy strict on new 2.x generics.
- Port allocation in CI for the HTTP test: bind port 0 to find a free port, then pass it; retry once on a clash.

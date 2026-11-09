# Spec: move memkernel to mcp 2.x (#95)

Origin: `origin/2026-11-08-issue-95.md`. Facts below were checked on 2026-11-08 against the mcp 2.3.0 and
mcp-types 2.3.0 wheels (source read, not executed) and a `pip install --dry-run` resolve on Python 3.13.

## Checked facts

- **The break is hard.** In mcp 2.x, `mcp.server.fastmcp` raises `ModuleNotFoundError` on import ("FastMCP was
  renamed to MCPServer"). A range spanning both majors needs an import switch in every module that touches the SDK.
- **What memkernel uses, and where it went in 2.3.0:**

  | memkernel uses (1.x) | mcp 2.3.0 |
  |---|---|
  | `FastMCP(name, host=, port=, lifespan=)` | `MCPServer(name, lifespan=)`; `host`/`port` are `run()` arguments |
  | `Context[S, L, R]` from `mcp.server.fastmcp.server` | `Context[L, R]` from `mcp.server.mcpserver` |
  | `ctx.request_context.lifespan_context` | unchanged |
  | `server.get_context()` in the `memory://status` resource | gone; a static resource may not take a `Context` parameter either |
  | `server.tool()`, `server.resource(uri)`, `server.run(transport=)` | kept |
  | `mcp.shared.memory.create_connected_server_and_client_session` (e2e tests) | gone; `mcp.client.Client(server)` connects in-process |
  | `ClientSession`, `StdioServerParameters`, `stdio_client` (wiring check) | kept |
  | `mcp.types.CallToolResult`, `TextContent` | kept (re-exported from `mcp-types`) |

- **Older hosts keep working.** 2.3.0 accepts the handshake versions 2024-11-05, 2025-03-26, 2025-06-18 and
  2025-11-25, the same set 1.30.0 accepts, and adds 2026-07-28.
- **One environment resolves.** memkernel's dependencies with `mcp>=2.3,<3` and `wiki-studio[mcp]==0.9.0` resolve:
  mcp 2.3.0, mcp-types 2.3.0, chromadb 1.5.9, fastapi 0.162.2, pydantic 2.14.3, starlette 1.10.0. 2.x adds runtime
  dependencies `mcp-types`, `httpx2`, `opentelemetry-api`, `pyjwt[crypto]`; `httpx2` installs beside `httpx`.
- **Neither real transport is tested today** (as the issue says): the e2e tests use the in-memory pair, and
  Streamable HTTP is checked only by its setting reaching `server.run()`.

## User Scenarios

- **US1:** a user installs `memkernel[wiki]` and `wiki-studio[mcp]` with one `pip install` into one environment and
  registers both servers, instead of keeping wiki-studio's server in a second environment.
- **US2:** a host (Claude Code, Kiro) that registered memkernel before upgrading keeps working: same command, same
  tools, same resource, same transports.

## Requirements

- **FR-001** memkernel depends on mcp 2.x per D1, and runs on it: the server, the nine tools, the
  `memory://status` resource, stdio and Streamable HTTP.
- **FR-002** `memory://status` reads the service without `get_context()`: the lifespan publishes its context to
  the resource through the server factory's closure.
- **FR-003** The e2e tests use the 2.x in-process client; `test_tool_count_under_10` still pins the exact tool set.
- **FR-004** New end-to-end tests, per D2: a stdio roundtrip against the server started as a subprocess, and a
  Streamable HTTP roundtrip with a live client against the running server (retain, then recall finds it), both
  fast; plus one `slow` stdio roundtrip against the real `memkernel` command.
- **FR-005** A decision record, `docs/adr/ADR-011-mcp-2.md`, as `CLAUDE.md` requires for dependency changes.
- **FR-006** README: the two-environment section becomes a one-environment install; CHANGELOG under
  `[Unreleased]` names the break for Python embedders (`create_server()` returns `MCPServer`; `mcp<2` is no longer
  supported). `CLAUDE.md`'s layout line says MCPServer.
- **FR-008** (found in build) A tool's `ValueError` reaches the client as "Error executing tool <name>: <message>",
  as on 1.x: mcp 2.x passes the text of a `ToolError` only, so memkernel re-raises `ValueError` as `ToolError`.
  Other exceptions stay hidden, as mcp 2.x intends. The e2e tests pin two of these messages.
- **FR-007** The wiring check (`eval/lifecycle-suite/wiring/wiring_check.py`) keeps working on 2.x, or its frozen
  status is respected and recorded.

## Constraints / What NOT to Build

- No change to tool names, arguments, results, the resource URI or settings (`MEMKERNEL_*`).
- No new MCP features from 2.x (tasks, elicitation, the 2026-07-28 flow, caching).
- Not a dual-major code path (D1).
- No version bump here; the release PR bumps `pyproject.toml` and `__init__.py` together (D3).
- Do not edit frozen evaluation artifacts (`arms/*/config.frozen.json`, `minimal-block-0.5.md`, receipts).

## Key Entities

- `create_server()` / `MCPServer[MemKernelContext]`, `MemKernelContext`, the `memory://status` resource,
  `register_memory_tools` / `register_wiki_tools`, the e2e test client.

## Success Criteria

- **SC-1** Fast suite, e2e tests, ruff, mypy strict and coverage ≥ 80% pass on mcp 2.x.
- **SC-2** The two fast FR-004 tests pass and run in CI; the `slow` one passes locally.
- **SC-3** `pip install --dry-run` of `memkernel[wiki]` (from the branch) with `wiki-studio[mcp]==0.9.0` resolves.
- **SC-4** `memkernel --version`, `--help` and a real stdio session from a host-shaped client work.

## Decisions (the owner's, 2026-11-08)

- **D1. Range:** hard move to `mcp>=2.3,<3`. It is the only range that co-installs with `wiki-studio[mcp]`
  (`>=2.3`), and hosts are unaffected because the wire protocol versions are the same. Not a range spanning both
  majors.
- **D2. Transport tests: both.** (a) A test launcher that calls `create_server()` with the tests' `MockEmbedding`
  and the real `server.run(transport)` in a subprocess, for stdio and for Streamable HTTP: fast, runs in CI.
  (b) One `slow` test that starts the real `memkernel` command (real model) over stdio and does a roundtrip: covers
  the entry point; CI does not run it.
- **D3. Release:** no version change in this PR; a later release PR ships it as 0.9.0.

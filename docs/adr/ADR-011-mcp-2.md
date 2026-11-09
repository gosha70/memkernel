# ADR-011: memkernel moves to the mcp 2.x Python SDK

Status: accepted (2026-11-08). Specified in `specs/memkernel-0-9-mcp2` (gosha70/memkernel#95).

## Context

memkernel pinned `mcp>=1.25,<2`. wiki-studio's optional MCP server (`wiki-studio[mcp]`, from 0.8.0) needs
`mcp>=2.3,<3`, so the two could not share one environment: `pip install memkernel[wiki] wiki-studio[mcp]` failed
with `ResolutionImpossible`, and the README documented a second environment for wiki-studio's server.

mcp 2.x is a hard break for server code. `mcp.server.fastmcp` raises `ModuleNotFoundError` on import; `FastMCP` is
now `mcp.server.mcpserver.MCPServer`. For what memkernel uses:

- `host` and `port` moved from the constructor to `run("streamable-http", host=, port=)`;
- `Context` takes two type parameters instead of three; `ctx.request_context.lifespan_context` is unchanged;
- `get_context()` is gone, and a static resource may not take a `Context` parameter;
- only a `ToolError` keeps its message on the way to the client; any other exception becomes a bare
  "Error executing tool <name>";
- `mcp.shared.memory.create_connected_server_and_client_session` is gone; `mcp.Client(server)` connects in process;
- `CallToolResult.isError` is `is_error`.

The wire protocol is not part of the break: 2.3.0 accepts the handshake versions 2024-11-05 to 2025-11-25, the
same set as 1.30.0, and adds 2026-07-28.

## Decision

1. **Require `mcp>=2.3,<3`.** Not a range spanning both majors: that needs an import switch in every module that
   touches the SDK and a CI matrix over both, and only `>=2.3` co-installs with `wiki-studio[mcp]` anyway.
2. **Keep every visible behaviour.** Tool names, arguments and results, the `memory://status` resource, the
   transports and the `MEMKERNEL_*` settings are unchanged. In particular:
   - a tool's `ValueError`, memkernel's way of reporting a caller's mistake, is re-raised as `ToolError`
     (`memkernel.mcp.tools.errors.reported_errors`), so the client still reads
     "Error executing tool <name>: <message>"; any other exception stays hidden, as mcp 2.x intends;
   - `memory://status` reads the lifespan context through the server factory's closure.
3. **Test the real transports.** Besides the in-process tests, a stdio roundtrip against the server started as a
   subprocess and a Streamable HTTP roundtrip against a running server run in the fast suite; a `slow` test runs
   the installed `memkernel` command over stdio with the real model.

## Consequences

- One environment holds `memkernel[wiki]` and `wiki-studio[mcp]`; the README's two-environment install goes.
- New transitive dependencies: `mcp-types`. (`httpx2`, `opentelemetry-api` and `pyjwt` were already in the lock
  through other packages.) `httpx-sse` leaves the lock.
- Hosts that registered memkernel (Claude Code, Kiro, the templates under `templates/`) need no change.
- Python code that embeds memkernel's server breaks if it pins `mcp<2`, or uses the `FastMCP` type that
  `create_server()` returned: it now returns `MCPServer[MemKernelContext]`. The CHANGELOG says so.
- A crash inside a tool (anything but `ValueError` or a `ToolError`) no longer shows its text to the client.

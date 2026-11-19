# Spec: one memkernel store across several coding tools (#107)

Status: approved by the owner, 2026-11-19: D1–D5 as written below. Drafted overnight on 2026-11-18 on the owner's
instruction to open a PR per issue; nothing here is built yet. The host and origin checks shipped on their own
(#149, for #148).

## Checked facts (`main` at `4ef72c2`)

- **Real transport tests exist.** `tests/e2e/test_mcp_transports.py` (#95) starts the server as a subprocess and
  drives it over stdio and over Streamable HTTP (`test_streamable_http_roundtrip_against_a_running_server`), and
  through the installed `memkernel` command. #107's "no test starts a real HTTP server" predates it. No test has
  two clients on one server.
- **Several processes can write to one persisted store.** Four writer processes, 60 records each, on one
  `chroma_persist_path`: 240 records stored, no errors, recall correct afterwards, in three runs (chromadb 1.5.9;
  measured 2026-11-18).
- **A running server missed other processes' writes in relevance recall** (#139): chromadb caches its dense index
  per process and the BM25 index was built once. Metadata reads (`list_memories`, `get`,
  `recall(order="newest")`) were not affected. Fixed on `main` (#140, reverted by mistake in #145, re-landed with
  an `ask` follow-up in #146): a count check before relevance recall. It affected the single-tool Claude Code setup
  too (hook-written checkpoints, startup capture).
- **A non-loopback HTTP bind had no host or origin check** (#148). `MCPServer` turns the SDK's DNS-rebinding
  protection on by itself for a loopback bind (`127.0.0.1`, `localhost`, `::1`), so the default setup was protected;
  `MEMKERNEL_HOST=0.0.0.0` or a LAN address got no check, and a `0.0.0.0` bind also answers on `127.0.0.1`. There
  is no authentication in any setup. #149 fixes the non-loopback case, with `MEMKERNEL_ALLOWED_HOSTS`.
- **Store locks are cross-process** (`fcntl` on POSIX, memkernel-0-7-store-locks): the wiki import and tag writes
  are serialised across processes; on Windows they run unlocked with a warning.
- **Session-start context is automatic only in Claude Code** (`templates/hooks/session-start.py`) **and Kiro**
  (`templates/kiro/`). `memkernel` has no subcommands: `memkernel.mcp.server:main` accepts only `--version` and
  `--help`, and starts the server otherwise.
- **The other tools, from their current documentation** (2026-11-18; the sources are listed in the PR):

  | Tool | MCP stdio / HTTP | MCP config (project) | Instructions read at start | Session-start hook | How hook output reaches the model |
  |---|---|---|---|---|---|
  | Codex CLI | yes / yes | `.codex/config.toml` (trusted projects), `[mcp_servers.<name>]` | `AGENTS.md` | `SessionStart` in `.codex/hooks.json`; each hook reviewed and trusted by hash | plain stdout, or `hookSpecificOutput.additionalContext`; about 2,500 tokens by default |
  | Cursor | yes / yes | `.cursor/mcp.json` | `.cursor/rules/*.mdc` with `alwaysApply: true`; `AGENTS.md` | `sessionStart` in `.cursor/hooks.json`, fire-and-forget; also loads Claude Code's `.claude/settings.json` hooks | JSON `additional_context`; a staff-confirmed bug drops it on the first request in the Agents Window (3.24.9, 3.25.6) |
  | Antigravity | yes / yes (no SSE) | `.agents/mcp_config.json` (`command` or `serverUrl`) | `AGENTS.md`, `GEMINI.md`, `.agents/rules/*.md` with `trigger: always_on` | `SessionStart` in `.agents/hooks.json`, 30 s default | JSON `injectSteps`; the docs' examples disagree on the `systemMessage` shape |
  | Claude Code | yes / yes | `.mcp.json` | `CLAUDE.md`; `AGENTS.md` from v2.1.277 | `SessionStart` | plain stdout or `additionalContext`; 10,000 characters |

## User Scenarios

1. A developer uses Claude Code in the morning and Codex in the afternoon on one project. Codex's session starts with
   the latest checkpoint and the project's decisions that Claude Code's sessions stored, from the same store.
2. Two tools run at once on one project, each starting its own memkernel over stdio. A decision one of them stores
   is recalled by the other in the same hour.
3. A developer prefers one long-running server: they start it once over Streamable HTTP and register its URL in each
   tool.

## Requirements

- **FR-001 Several stdio servers (D1).** Supported: each tool starts its own `memkernel` on the shared store. Builds
  on the #139 fix (#146). A test starts two server subprocesses over stdio on one store: a `retain` through one is returned by a
  relevance `recall` through the other.
- **FR-002 One shared HTTP server.** A README section, "One store across tools", shows starting memkernel once with
  `MEMKERNEL_TRANSPORT=streamable-http` and registering `http://127.0.0.1:8765/mcp` in Claude Code (`.mcp.json`),
  Codex (`.codex/config.toml`), Cursor (`.cursor/mcp.json`) and Antigravity (`.agents/mcp_config.json`,
  `serverUrl`). A test runs two MCP clients against one server subprocess: a `retain` through one is recalled
  through the other.
  - **Local only.** The host and origin checks follow `MEMKERNEL_HOST`, with `MEMKERNEL_ALLOWED_HOSTS` for a
    wildcard bind; that ships on its own as #149 (#148). The README section says "local only, no authentication".
- **FR-003 `memkernel session-start` (D2).** A subcommand that reads the hook's JSON from stdin when there is one
  (for `source` and `session_id`), runs `MemoryLifecycle.on_session_start`, and prints the block in the shape
  `--format` names: `plain` (stdout text: Claude Code, Codex), `cursor` (`{"additional_context": …}`),
  `antigravity` (`{"injectSteps": [{"systemMessage": …}]}`). `--max-chars` cuts the block, keeping its headings, for
  tools with a smaller cap (D5). `memkernel` with no arguments still starts the server.
  - **No spool line.** `session-start` writes no `started` line to the session spool, for any format: the spool
    pairs a start with an end, and only Claude Code's hooks write both. A tool that never writes `ended` would leave
    every Claude Code startup reporting sessions that "recorded no end". Capture (#134) therefore stays a Claude Code
    feature.
  - **`source` mapping.** Codex's `SessionStart` passes the same `source` values as Claude Code (`startup`,
    `resume`, `clear`, `compact`, `fork`), mapped one to one: `resume` and `fork` print nothing, `compact` prints the
    recovery block. Cursor's `sessionStart` and Antigravity's `SessionStart` pass no `source`, so they get the
    `startup` block.
- **FR-004 Templates (D3).** Under `templates/codex/`, `templates/cursor/`, `templates/antigravity/`: the MCP
  registration (stdio and HTTP), an instruction file telling the agent to call
  `recall(checkpoint_only=true, order="newest")` and recall the project's decisions at the start of a session, and,
  where D3 says so, a session-start hook calling `memkernel session-start`. The wiki workflow stays in one place
  (#86): the instruction files link to it.
- **FR-005 Docs.** README "One store across tools": the two setups (FR-001, FR-002), the per-tool templates, which
  tool versions they follow, and the limits: local only, no authentication; Windows store locks run unlocked; #139's
  limit; capture only from Claude Code sessions. CHANGELOG under Added (and under Security for the host and origin
  checks).

## Constraints / What NOT to Build

- No hosted service, sync service or hub (the owner's scope: local and self-hosted).
- No capture of other tools' transcripts: S2's reader is Claude Code's; other readers are later work (#59).
- No new MCP tool; no change to the stored data.
- No hook template for a tool whose hook output format is unverified or unreliable (D3).

## Key Entities

- **Format:** how `memkernel session-start` wraps the block for one tool's hook.

## Success Criteria

- **SC-1** Two stdio server subprocesses on one store: a record retained through one is recalled through the other
  (FR-001).
- **SC-2** Two clients on one HTTP server subprocess: likewise (FR-002). A request with a foreign `Host` or
  `Origin` header is refused.
- **SC-3** `memkernel session-start --format plain|cursor|antigravity` prints the same block as the Claude Code hook,
  in each shape; `--max-chars` keeps the headings; no arguments still starts the server; no spool line is written
  (FR-003).
- **SC-4** Each template parses as its tool's documented format (TOML, JSON, `.mdc` frontmatter, rule frontmatter).
- **SC-5** Fast suite, ruff, mypy strict, coverage ≥ 80%; the MCP tool set unchanged.

## Decisions (the owner's, 2026-11-19)

- **D1 Several stdio servers: support them** (the #139 fix is on `main`), and document the shared HTTP server as the alternative
  for a long-running setup: both setups are supported. Stdio-per-tool is what every tool's MCP config does by default,
  and the #139 fix makes it correct.
- **D2 A `session-start` subcommand on `memkernel`**, not a separate command.
- **D3 Where a hook replaces the instruction:**
  - **Codex: hook and `AGENTS.md`.** Its `SessionStart` is documented, takes plain stdout, and matches Claude
    Code's JSON shape.
  - **Cursor: the `alwaysApply` rule only.** Its `sessionStart` is fire-and-forget and loses its context on the
    first request in the Agents Window (staff-confirmed, unfixed). Cursor can also load Claude Code's hooks; the
    README says so, without relying on it.
  - **Antigravity: the `always_on` rule only**, until its `injectSteps` shape is verified in a live session (the
    docs' examples disagree).
- **D4 The tools:** Codex, Cursor and Antigravity, as #107 names (Claude Code and Kiro exist).
- **D5 Codex's cap: `--max-chars 6000`.**
  - **The cap:** about 2,500 tokens by default per model-visible hook message.
  - **The arithmetic:** at about 4 characters per token that is about 10,000 characters, but code-heavy text runs
    nearer 3, about 7,500. The block holds code and paths, so 8,000 could pass the cap.
  - **Over the cap,** Codex saves the output to a file and shows a head-and-tail preview (its hooks docs), so it
    cuts the output, not drops it. Even so, a cut that removes the middle of the block loses the context section.
  - **6,000,** a 20% margin under the code-heavy estimate. It changes nothing in Codex's own settings.

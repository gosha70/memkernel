# Spec: one memkernel store across several coding tools (#107)

Status: draft, 2026-11-18. Written overnight on the owner's instruction to open a PR per issue; D1–D5 are
**proposed, for the owner's decision**, and nothing here is built yet.

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
  `recall(order="newest")`) were not affected. #140 fixes it with a count check before relevance recall. This
  affected the single-tool Claude Code setup too (hook-written checkpoints, startup capture).
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
  on #140. A test starts two server subprocesses over stdio on one store: a `retain` through one is returned by a
  relevance `recall` through the other.
- **FR-002 One shared HTTP server.** A README section, "One store across tools", shows starting memkernel once with
  `MEMKERNEL_TRANSPORT=streamable-http` and registering `http://127.0.0.1:8765/mcp` in Claude Code (`.mcp.json`),
  Codex (`.codex/config.toml`), Cursor (`.cursor/mcp.json`) and Antigravity (`.agents/mcp_config.json`,
  `serverUrl`). A test runs two MCP clients against one server subprocess: a `retain` through one is recalled
  through the other.
- **FR-003 `memkernel session-start` (D2).** A subcommand that reads the hook's JSON from stdin when there is one
  (for `source` and `session_id`), runs `MemoryLifecycle.on_session_start`, and prints the block in the shape
  `--format` names: `plain` (stdout text: Claude Code, Codex), `cursor` (`{"additional_context": …}`),
  `antigravity` (`{"injectSteps": [{"systemMessage": …}]}`). `--max-chars` cuts the block, keeping its headings, for
  tools with a smaller cap (D5). `memkernel` with no arguments still starts the server.
- **FR-004 Templates (D3).** Under `templates/codex/`, `templates/cursor/`, `templates/antigravity/`: the MCP
  registration (stdio and HTTP), an instruction file telling the agent to call
  `recall(checkpoint_only=true, order="newest")` and recall the project's decisions at the start of a session, and,
  where D3 says so, a session-start hook calling `memkernel session-start`. The wiki workflow stays in one place
  (#86): the instruction files link to it.
- **FR-005 Docs.** README "One store across tools": the two setups (FR-001, FR-002), the per-tool templates, which
  tool versions they follow, and the limits (Windows: store locks run unlocked; #139's limit). CHANGELOG under Added.

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
- **SC-2** Two clients on one HTTP server subprocess: likewise (FR-002).
- **SC-3** `memkernel session-start --format plain|cursor|antigravity` prints the same block as the Claude Code hook,
  in each shape; `--max-chars` keeps the headings; no arguments still starts the server (FR-003).
- **SC-4** Each template parses as its tool's documented format (TOML, JSON, `.mdc` frontmatter, rule frontmatter).
- **SC-5** Fast suite, ruff, mypy strict, coverage ≥ 80%; the MCP tool set unchanged.

## Decisions (proposed, for the owner)

- **D1 Several stdio servers: support them** (after #140), and document the shared HTTP server as the alternative
  for a long-running setup. Alternative: support only the shared server and document stdio-per-tool as
  unsupported. Recommended: support both, since stdio-per-tool is what every tool's MCP config does by default and
  #140 makes it correct.
- **D2 A `session-start` subcommand on `memkernel`**, not a separate command. Recommended.
- **D3 Where a hook replaces the instruction:**
  - **Codex: hook and `AGENTS.md`.** Its `SessionStart` is documented, takes plain stdout, and matches Claude
    Code's JSON shape.
  - **Cursor: the `alwaysApply` rule only.** Its `sessionStart` is fire-and-forget and loses its context on the
    first request in the Agents Window (staff-confirmed, unfixed). Cursor can also load Claude Code's hooks; the
    README says so, without relying on it.
  - **Antigravity: the `always_on` rule only**, until its `injectSteps` shape is verified in a live session (the
    docs' examples disagree).
  Recommended as listed.
- **D4 The tools:** Codex, Cursor and Antigravity, as #107 names (Claude Code and Kiro exist). Recommended.
- **D5 Codex's cap:** about 2,500 tokens by default, below the 9,000-character block. The Codex template passes
  `--max-chars 8000`. Alternative: raise Codex's per-hook `additionalContextLimit` in the template. Recommended:
  `--max-chars 8000`, which changes nothing in Codex's own settings.

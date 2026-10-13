# MemKernel in Kiro

MemKernel is a plain stdio MCP server, so [Kiro](https://kiro.dev) (the successor of
Amazon Q Developer in the IDE; the Q Developer CLI became the Kiro CLI) connects to it
like any other MCP server. Three files give Kiro the same memory protocol Claude Code
gets from `CLAUDE.md` and the hook scripts:

| File in this folder | Copy to | Role |
|---|---|---|
| `settings/mcp.json` | `.kiro/settings/mcp.json` (workspace) or `~/.kiro/settings/mcp.json` (all workspaces) | Registers the server and pre-approves the everyday tools |
| `steering/memory.md` | `.kiro/steering/memory.md` | The memory instructions, loaded into every interaction (`inclusion: always`) |
| `hooks/memkernel.json` | `.kiro/hooks/memkernel.json` | Lifecycle hooks: recall at session start, retain at turn end, a manual checkpoint |

## 1. Install the server

```bash
pipx install memkernel      # or: uv tool install memkernel
which memkernel
```

The Kiro desktop app may not inherit your shell `PATH`. If the server fails to start,
put the absolute path printed by `which memkernel` in the `command` field.

## 2. Register the MCP server

Copy `settings/mcp.json`, then edit two values:

- `MEMKERNEL_PROJECT_ID`: a short identifier for the project (memories are isolated per project).
- `MEMKERNEL_CHROMA_PERSIST_PATH`: an absolute data directory. The default
  (`.memkernel/chroma`) is relative to the server's working directory, which an IDE may not
  set to the workspace. Kiro expands `${HOME}` and other environment variables in `env`.

`autoApprove` lists the tools Kiro may call without a prompt. The template approves
`recall`, `get`, `ask`, `retain` and `consolidate`; `forget`, `promote`, `wiki_export` and
`wiki_import` still ask. Use `"*"` to approve everything.

To share one long-running server between tools, run
`MEMKERNEL_TRANSPORT=streamable-http memkernel` and register a `url` entry pointing at
`http://127.0.0.1:8765/mcp` instead of `command`.

## 3. Steering file

Copy `steering/memory.md` as is. The YAML front matter must be the very first bytes of
the file. Kiro also reads a root `AGENTS.md` as an always-on steering file, so the same
section can live there if you want one file for Kiro, Codex and Claude Code.

## 4. Hooks

Kiro has no compaction event, so the Claude Code hook scripts (`templates/hooks/`) do not
port one to one. `hooks/memkernel.json` maps the protocol onto Kiro's triggers:

| MemKernel step | Kiro trigger | What the hook asks the agent to do |
|---|---|---|
| Session start | `SessionStart` | Recall the last checkpoint and long-term context, read the wiki index |
| While working | `Stop` (end of each agent turn) | Retain durable decisions, facts, procedures and the current task state |
| Before compaction | `Manual` ("memkernel: save checkpoint") | Retain a checkpoint episode, consolidate, promote |

The `Stop` hook runs after every turn and costs a few hundred tokens each time. Delete it
if that is too chatty; the manual checkpoint and the session-start recall are enough for
most sessions.

Hook files use the Kiro CLI 3.x / IDE 1.x format: `.kiro/hooks/<name>.json` with
`version: "v1"` and PascalCase triggers. Older IDE builds read `.kiro.hook` files with
lowercase trigger names (`promptSubmit`, `agentStop`); if your Kiro still uses those,
rename the triggers and the file. Check the current format at
<https://kiro.dev/docs/hooks/>.

## Kiro CLI custom agents

A custom agent in `.kiro/agents/<name>.json` carries its own `mcpServers` and `hooks`
blocks, and does not load steering files automatically. Paste the server entry from
`settings/mcp.json` into the agent's `mcpServers`, add `.kiro/steering/memory.md` to its
`resources`, and use the agent hook names `agentSpawn` (session start) and `stop`.

## Amazon Q Developer CLI (legacy)

The old Q Developer CLI reads the same `mcpServers` JSON from `~/.aws/amazonq/mcp.json`.

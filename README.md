<h1>
  <img src="https://raw.githubusercontent.com/gosha70/memkernel/main/docs/assets/memkernel-logo.png" alt="MemKernel logo: a glowing memory core on three stacked tiers" width="110" align="absmiddle">
  MemKernel
</h1>

[![CI](https://github.com/gosha70/memkernel/actions/workflows/ci.yml/badge.svg)](https://github.com/gosha70/memkernel/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/memkernel)](https://pypi.org/project/memkernel/)
[![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-blue)](pyproject.toml)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-green)](LICENSE)

**Site:** [memkernel.dev](https://memkernel.dev) · **Package:** [pypi.org/project/memkernel](https://pypi.org/project/memkernel/)

Code-aware memory server for AI coding copilots.

MemKernel gives Claude Code (and any MCP-compatible copilot) persistent memory across sessions. When Claude compacts context or a session ends, project decisions, conventions, and code understanding are normally lost. MemKernel stores them in a local vector database and retrieves them on demand.

**Key differentiator**: MemKernel understands code as code. It uses tree-sitter AST parsing to chunk files at function and class boundaries, embeds chunks with scope context, and provides hybrid search (dense + BM25) for both semantic queries and exact identifier lookup.

**Tiered memory (0.2)**: memories live in three tiers with different persistence rules — *working* (the current task, hours), *short-term* (episodes and observations, decays unless recalled) and *long-term* (decisions, conventions, facts, procedures, code; never decays, replaced by supersession). Recall ranks by relevance, recency and importance; `consolidate` and `promote` move what proved useful into long-term memory; an LLM-wiki bridge keeps a human-readable, git-versioned copy of long-term knowledge. Design: [`docs/architecture/memory-tiers.md`](docs/architecture/memory-tiers.md).

## What MemKernel is, and what it is not

**It is:**

- **Persistent memory for a coding agent.** What the agent retains survives context compaction and the end of a session, in a local ChromaDB store per project.
- **Explicit.** The agent decides what to retain (decisions, conventions, facts, code snapshots, tasks) and what to recall. The lifecycle hooks only automate the protocol around that: checkpoint before compaction, recovery after it, consolidation and revalidation at session start.
- **Code-aware.** AST chunking, hybrid search that finds identifiers as well as meaning, and revalidation of `code` memories against the files they came from.
- **No mandatory generative LLM.** Default retrieval uses a local sentence-transformer embedding model plus BM25 and RRF; nothing generates text inside MemKernel. `ask` with the built-in reasoner returns the best-matching chunks; synthesis is the agent's job, or an optional external reasoner's.

**It is not:**

- **A token optimizer or context compressor.** MemKernel does not shrink the context window, compress prompts, or lower model cost by itself. It adds tool calls and returned content to a session. Any token saving comes from the agent re-reading fewer files or documents after a resume; that is a side effect to measure, not a promise.
- **A replacement for files, specs and git.** Progress notes, task lists and review records already carry state between sessions. MemKernel adds retrieval by meaning and identifier, tiers with decay, supersession and revalidation on top. When a file already holds everything the next session needs, expect no gain.
- **An index of the whole repository.** `code` memories are the snapshots the agent chose to retain, not an automatic scan of every file.
- **A cross-project knowledge base.** One store per project id. Sharing is deliberate: a second server with a shared id, or the wiki bridge.

**Evidence.** `eval/run_eval.py` measures retrieval (recall@k, precision@k, MRR). The 0.5 lifecycle evaluation, a **maintainer-run supplemental evaluation** (memkernel's own runner, preregistered and announced in [#17](https://github.com/gosha70/memkernel/issues/17) before the run), ran the same agent in seven arms on 20 tasks: [report](eval/lifecycle-suite/report-0.5.0.md). **No gain is claimed.** Against files alone (`claude_md`), memkernel's memory store was ahead on 6 tasks, behind on none and tied on 14 (Holm-adjusted p 0.0625: "no detectable difference"; with so many ties this task set could not have reached significance); against earlier transcripts (`fs_grep`) it was equivalent. Two of the four task groups hit a ceiling, every arm passing every trial. The report's disclosures list its deviations and known defects. Results are published with the cases that show no gain; the 0.5 report is the latest evaluation, and 0.6.0 had no new measured run. The next task set, `lc-correct` ([#90](https://github.com/gosha70/memkernel/issues/90)), measures whether a correction reaches the agent, including through a governed wiki-studio wiki. It is built and exercised with a stub agent; its calibration and measured run each wait for a preregistration and budget.

---

## Requirements

- Python 3.11 – 3.13 (the package declares `Requires-Python >=3.11,<3.14`; pip reports "from versions: none" when the installing interpreter is outside that range)
- [Poetry](https://python-poetry.org) (for development installs)

---

## Install

MemKernel is a Python package on PyPI. Its `memkernel` command is the MCP server. There is no npm package: an `npx` install someone suggests is a hallucination.

**Recommended: an isolated install with [pipx](https://pipx.pypa.io)**, which puts the `memkernel` command on your PATH without touching any other Python environment:

```bash
pipx install memkernel
# if pipx's default interpreter is outside 3.11–3.13:
pipx install --python python3.11 memkernel
# optional: wiki-studio lint and health findings on wiki_export (ADR-010)
pipx install "memkernel[wiki]"
pipx inject memkernel "wiki-studio>=0.7.0,<1"   # add it to an existing install
```

**As a library inside a project**, install it into that project's virtual environment:

```bash
pip install memkernel        # or: poetry add memkernel
```

Avoid a plain `pip install memkernel` into a shared or system interpreter (Homebrew's `python3`, for example). MemKernel pins `chromadb` 1.x and recent `cffi`, so pip will replace older copies and can break unrelated tools that need them.

Verify the install with `pipx list` or `which memkernel`. Running `memkernel` with no arguments starts the MCP server on stdio and waits for a client; `memkernel --version` and `memkernel --help` print and exit.

---

## Add to Claude Code

### 1. Register the MCP server

Add MemKernel to `.claude/settings.json` in your project:

```json
{
  "mcpServers": {
    "memkernel": {
      "command": "/Users/you/.local/bin/memkernel",
      "args": [],
      "env": {
        "MEMKERNEL_PROJECT_ID": "my-project",
        "MEMKERNEL_CHROMA_PERSIST_PATH": "/Users/you/.memkernel/my-project"
      }
    }
  }
}
```

Replace `my-project` with a short identifier for the project — memories are isolated per project. Use the absolute path of the command (`which memkernel` prints it) because Claude Code does not necessarily see the PATH changes your shell profile makes, and an absolute `MEMKERNEL_CHROMA_PERSIST_PATH` keeps the store outside the repository. On first server initialization, MemKernel downloads the embedding model (about 90 MB) if it is not already cached: `build_service()` loads the sentence-transformers model when the MCP server starts, before any tool call, so the first connection can take a minute. Later starts and every tool call are fast.

<details>
<summary>Troubleshooting the install</summary>

- **`pipx install memkernel` says "No matching distribution found"** — pipx used an interpreter outside 3.11–3.13. Pass one explicitly: `pipx install --python /opt/homebrew/opt/python@3.11/bin/python3.11 memkernel`.
- **`bash: /some/old/path/memkernel: No such file or directory`** right after reinstalling — the shell cached the old location. Run `hash -r` (bash) or `rehash` (zsh), then `which memkernel`.
- **`memkernel --help` seems to hang** on versions before 0.4.0 — the command had no flags and started the server; press Ctrl-C. From 0.4.0 on, `--help` and `--version` print and exit.
- **The first MCP connection is slow or times out** — the server is downloading the embedding model at startup (see above). Wait for it once, or pre-warm it with `python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"` in the same environment.
- **A global pip install broke another tool** (for example `langchain-chroma` wanting `chromadb < 0.6`) — uninstall memkernel from that interpreter, reinstall the versions the other tool needs, and install memkernel with pipx instead.

</details>

### 2. Add memory instructions to CLAUDE.md

Copy the contents of [`templates/claude-memory-instructions.md`](templates/claude-memory-instructions.md) into your project's `CLAUDE.md`. This tells Claude when and how to call the memory tools.

### 3. (Optional) Install lifecycle hooks

Copy the hook scripts from [`templates/hooks/`](templates/hooks/) to `.claude/hooks/` and register them in `.claude/settings.json`:

| Hook | Claude Code event | What it does |
|------|-------------------|--------------|
| `session-start.py` | `SessionStart` | By `source`: on `startup` and `clear`, consolidates, recovers the latest checkpoint and long-term context, lists promotion candidates; on `compact`, the recovery after a compaction (the latest checkpoint the agent saved, with its age, and long-term context; no consolidation); on `resume` and `fork`, nothing |
| `pre-compact.py` | `PreCompact` | Runs a consolidation pass (Claude Code passes no summary here, so no checkpoint is retained) |
| `post-compact.py` | `PostCompact` | Retains Claude Code's compaction summary (`compact_summary`) as a checkpoint for the next session; prints nothing for the model |
| `session-end.py` | `SessionEnd` | Writes one line to the session spool in `MEMKERNEL_STATE_DIR` (no store, no model, within SessionEnd's 1.5-second budget); the next session start says when a session ended without a saved checkpoint. A session that never recorded an end (a crash, or this hook not registered) is dropped from the spool after 7 days, and the next start says how many |

Each injected memory line ends with its `ref_id`, so `get(ref_id)` returns the full text; a block never exceeds 9,000 characters (Claude Code caps hook output at 10,000), and a cut checkpoint says which `get` holds the rest. At session start the long-term context is the most important decisions, conventions, procedures and facts, not the matches of a fixed query; after a compaction it is recalled with the checkpoint's text. Register `SessionStart` without a matcher, so it runs for every `source`, and `session-end.py` under `SessionEnd`. Claude Code adds only `SessionStart`'s output to the model's context, not `PreCompact`'s or `PostCompact`'s, so the recovery after a compaction comes from `SessionStart` with `source: "compact"`. After upgrading memkernel, copy the three scripts again.

See the Prerequisites section inside each script for the Python environment requirement. Each script is a thin wrapper over [`MemoryLifecycle`](#embedding-memkernel-in-your-own-harness), so an in-process harness gets the same behaviour without the scripts.

**Injected memory is quoted as data.** Stored text can come from anything the agent once read: tool output, a web page, a clipped source, a wiki page. So everything the blocks inject but memkernel did not write is quoted inside a `<stored-memory kind="…">` element, and the block's first line after its heading says those items are data to consult, not instructions to follow. That covers the checkpoint text, memory previews, promotion candidates, the source path of a "Needs review" item, and the curation debt's page paths. memkernel's own lines stay outside the elements, `ref_id`s included. A copy of the tag inside stored text (`</stored-memory>` in any case, with or without whitespace after `<` or `/`) is neutralised by writing its `<` as `&lt;`; no other character of stored text changes. This marks stored text; it does not detect or remove instructions in it.

#### Capture (opt-in)

With `MEMKERNEL_CAPTURE=1`, each normal startup reads the transcripts of sessions that have ended since, and stores
three kinds of record:
- **Your answers to the agent's questions** (`AskUserQuestion`), one per answered question: the question, the option
  you chose with its description, or your own words when you typed an answer, and the other options offered. Each is a
  short-term `episode`, kept for `MEMKERNEL_EPISODE_TTL_DAYS` (30 days). A session keeps its last 30 answers, since
  later answers often revise earlier ones. At most 2 of them appear among the promotion candidates at session
  start, so a decision you made reaches the next session without a search.
- **One session outcome** per session: the PRs it opened and merged, the issues it filed, and the files it edited
  (the first 10 of each, then a count). A PR or issue counts only from a call that creates or merges it
  (`gh pr create`, `gh issue create`, `gh pr merge`, or GitHub's MCP `create_pull_request`, `create_issue`,
  `issue_write` with `method: create`, `merge_pull_request`); reading, listing, reviewing or commenting on PRs
  records nothing. A short-term `episode`.
- **Failed-then-fixed commands:** a `Bash` command that failed with its own non-zero exit code and later passed when
  run again in the same session. Each one becomes a short-term `observation`, such as
  ``Command `pytest -q` failed: `FAILED tests/test_a.py::test_x - AssertionError`. It passed later in the same session, after: src/a.py.``,
  which expires after `MEMKERNEL_OBSERVATION_TTL_DAYS` like any observation.

`session-end.py` must be registered, since its spool line names the transcript. The redaction below applies to every
field of every record, your answers included.

- **Yields differ.** On the maintainer's local transcripts (78 sessions), 222 answers came from 17 sessions and 58
  sessions had an outcome, while failed-then-fixed matched 1 of 289 failed commands: agents usually change a command
  before running it again.
- **One recall result holds at most 3 captured records from any one session,** so a session with many answers
  cannot fill it; records you or the agent stored are not limited.
- **What counts as the same command:** the same text after removing a trailing `| tail`, `| head`, `| grep` or
  `2>&1`. A run counts as failed or passed only when its exit code is the command's own: a command piped into a
  filter without `set -o pipefail` reports the filter's exit code, so it is not judged. An error printed by a
  command that exits 0 is not captured.
- **Redaction is best-effort.** Before storing, each command, error line, answer and file path has these replaced
  with `[REDACTED]`: values of `…KEY=`, `…TOKEN=`, `…SECRET=`, `…PASSWORD=` assignments (and `.env` lines of that
  shape); `Authorization:` header values; tokens starting `AKIA`, `ghp_`, `gho_`, `github_pat_`, `sk-`, `xox`;
  private key blocks; credentials in URLs; and random-looking strings: 32 or more letters, digits and `+/=_-`
  that mix letters and digits and are not all hexadecimal (git SHAs stay; dashed UUIDs are redacted). A
  path-shaped string (starting with `/`, `~/`, `./` or `../`, or followed by a file extension) is judged component
  by component instead, so a captured error naming a path still matches later output; a component of 16 or more
  characters mixing uppercase, lowercase and digits (`ChromaBackendV2Test`) is redacted. A relative folder path
  with no extension, 32 or more characters with a digit, is redacted. A secret in any other shape is stored as
  written.
- **Limits per startup:** 3 seconds of capture (a session already started is finished), 20 records, 5 per session
  (the rest of a session's signals are dropped and counted). Sessions not reached wait for the next start. A
  transcript that cannot be read is retried at 3 startups, then dropped; one over 50 MB is dropped unread. An ended
  session not captured within 7 days is dropped. The "Previous sessions" section reports each of these.
- **Captured records are never promotion candidates**: the agent decides what to promote. They are quoted as
  stored memory wherever a block shows them. Each is keyed by its session and the failing call, so a capture that
  is interrupted and retried stores nothing twice. The same lesson captured in two sessions is two records, and can
  appear twice until they expire.

### 4. (Recommended) Keep memkernel's files and the hooks out of the agent's reach

Merge [`templates/claude-settings.example.json`](templates/claude-settings.example.json) into your project's `.claude/settings.json`. Its `permissions.deny` rules stop Claude's own file tools from editing four paths:
- `.memkernel/`, the store and state directory;
- `.claude/settings.json` and `.claude/settings.local.json`;
- `.claude/hooks/`.

So a session cannot rewrite the store, or what runs at the next session start. memkernel's server and hooks write `.memkernel/` themselves, not through Claude's tools, so they are unaffected.

Claude Code applies deny rules from a committed `.claude/settings.json` at once, and an allow rule cannot override them. `Edit(...)` rules cover every file-editing tool; a `Write(...)` rule would never match.

These rules have limits:
- **What they stop:** Claude's built-in file tools, the file commands Claude Code recognises in Bash (`cat`, `sed`, `tee`, ...) and redirections. Checked live with Claude Code 2.1.319: a write to each denied path was refused with "File is in a directory that is denied by your permission settings".
- **What they don't stop:** a program that writes files without naming them, such as a script or `python -c`. [Sandboxing](https://code.claude.com/docs/en/sandboxing) is the stronger boundary.
- **Other locations:** if you keep `MEMKERNEL_STATE_DIR` or the Chroma path elsewhere, change the first rule to match. A `/` rule anchors at the project, so a directory outside it needs an absolute `//` or a home-relative `~/` pattern, such as `Edit(~/.memkernel/**)`.
- **The rest of `.claude/`** (agents, commands, skills) stays editable, because teams often have the agent maintain them; it is a protected path, so edits there still prompt. Add `Edit(/.claude/**)` if yours should not be editable at all.

A mid-session "always allow" prompt, especially one asking for broad Bash or file access, deserves a second read: injected text can be what asked for it.

---

## Add to Kiro

Kiro (and the Kiro CLI, formerly Amazon Q Developer CLI) connects to MemKernel as a stdio MCP server. [`templates/kiro/`](templates/kiro/) holds the three files to copy into a workspace:

| Template | Destination | Role |
|----------|-------------|------|
| `settings/mcp.json` | `.kiro/settings/mcp.json` | Server entry with `env` and `autoApprove` |
| `steering/memory.md` | `.kiro/steering/memory.md` | Memory instructions, always included |
| `hooks/memkernel.json` | `.kiro/hooks/memkernel.json` | `SessionStart` recall, `Stop` retain, manual checkpoint |

[`templates/kiro/README.md`](templates/kiro/README.md) has the setup steps, the Kiro CLI custom-agent variant and the caveats (absolute persist path, hook format by Kiro version).

---

## One store across tools

Codex, Cursor and Antigravity can use the same memkernel store as Claude Code, so a decision recorded in one tool is
recalled in the next. Point every tool at the same store: the same `MEMKERNEL_PROJECT_ID`,
`MEMKERNEL_CHROMA_PERSIST_PATH` and `MEMKERNEL_STATE_DIR` (absolute paths). There are two ways to run it:

- **Each tool starts its own memkernel** over stdio, the default every MCP config uses. Several servers on one store
  are supported: a record one writes is recalled by the others.
- **One shared server.** Start it once with `MEMKERNEL_TRANSPORT=streamable-http memkernel` and register
  `http://127.0.0.1:8765/mcp` in each tool. **Local only, no authentication:** see
  [Streamable HTTP](#streamable-http) for the `Host`/`Origin` check and `MEMKERNEL_ALLOWED_HOSTS`.

**Agent and task ids decide which checkpoint a session recovers.** With `MEMKERNEL_TASK_ID` or `MEMKERNEL_AGENT_ID`
set, a session's checkpoints are saved in that task's (else that agent's) scope, and the session start recovers only
from there (see [Scope](#scope-agents-and-tasks)). So:
- tools continuing the same work set the **same `MEMKERNEL_TASK_ID`**; tools acting as the same agent set the **same
  `MEMKERNEL_AGENT_ID`**; a tool with different ids, or none, does not pick up the other's latest checkpoint;
- set the ids in the environment of **both the MCP server and the hooks** (for Codex: `config.toml`'s `env` table and
  the `hooks.json` command); ids passed only as `recall`/`retain` arguments never reach the hooks;
- keep a task id the same across the sessions that continue that work: a new id per session never recovers a
  checkpoint, and setting an id for the first time starts empty ("No checkpoint found yet"), since existing
  checkpoints are shared `project` ones;
- to hand work to any tool, save the checkpoint with `scope="project"`.

Templates, checked against each tool's documentation on 2026-11-18:

| Tool | Templates | Copy to | Session start |
|------|-----------|---------|---------------|
| Codex | [`templates/codex/`](templates/codex/): `config.toml` (stdio) or `config.http.toml`; `AGENTS.md`; `hooks.json` | `.codex/config.toml` (a trusted project); your `AGENTS.md`; `.codex/hooks.json` | a `SessionStart` hook runs `memkernel session-start --format plain --max-chars 6000` under `env` with the same `MEMKERNEL_*` values as `config.toml` (its `env` table reaches only the MCP server, and the hook is its own process, so set them in both files; use paths without spaces, since the command passes them unquoted); Codex runs no hook you have not trusted: open `/hooks` in Codex, review the memkernel hook and trust it, once and again after any change to it |
| Cursor | [`templates/cursor/`](templates/cursor/): `mcp.json` (stdio) or `mcp.http.json`; `rules/memkernel.mdc` | `.cursor/mcp.json`; `.cursor/rules/memkernel.mdc` | the rule (`alwaysApply: true`) tells the agent to recall the latest checkpoint and the project's decisions |
| Antigravity | [`templates/antigravity/`](templates/antigravity/): `mcp_config.json` (stdio) or `mcp_config.http.json`; `rules/memkernel.md` | `.agents/mcp_config.json`; `.agents/rules/memkernel.md` | the rule (`trigger: always_on`), likewise |

**Why only Codex gets a hook:** its `SessionStart` takes plain text on stdout, as Claude Code's does, and caps each
hook message at about 2,500 tokens, hence `--max-chars 6000`. Cursor's `sessionStart` hook is fire-and-forget and
drops its context on the first request in the Agents Window (a known Cursor bug), and Antigravity's hook output
shape is inconsistent in its own docs, so both use an always-on rule. `memkernel session-start` also prints the
block as `--format cursor` (`{"additional_context": …}`) and `--format antigravity` (`{"injectSteps": …}`), for when
those hooks become reliable.

Limits:
- **Capture** (`MEMKERNEL_CAPTURE`) reads Claude Code transcripts only. `memkernel session-start` writes no
  `started` line for its own session, so other tools' sessions are neither reported nor captured. On a startup it
  still handles the spool as a Claude Code start does: it removes ended Claude Code sessions, reports those that
  saved no checkpoint, and runs capture when `MEMKERNEL_CAPTURE` is on. So that report appears in whichever tool
  starts next.
- **On Windows** the store locks run unlocked, with a warning, so concurrent servers are not safe there.
- **A running server notices other processes' writes by the record count:** an addition and a deletion by others
  between two of its recalls go unseen until the next difference.

---

## Scope: agents and tasks

Several agents can share one store and still keep private notes. A memory's **scope** is `project` (the default:
every caller sees it), or private to one agent or one task. The caller names itself with `agent_id` and `task_id`
(tool arguments, or `MEMKERNEL_AGENT_ID` and `MEMKERNEL_TASK_ID` for the process), and sees `project` memories plus
its own agent's and task's. A caller with neither sees `project` memories only.

- `retain(..., scope="agent")` or `scope="task"` makes a memory private to the caller's own agent or task (refused
  without that id). Identical text in two scopes is two memories.
- **Checkpoints** without a `scope` go to the caller's task, else its agent, else `project`, and the latest-checkpoint
  recovery (the hooks' session start and compaction recovery, `recall(checkpoint_only=true, order="newest")`) reads
  only that scope, with no fallback to `project`. `scope="project"` is an explicit shared handoff.
- `promote` keeps the source's scope; `scope="project"` publishes. A private memory supersedes only memories in its
  own scope, so one agent cannot hide a shared memory from the others.
- Another agent's or task's memory is not found by `get`, `ask`, `forget` or `promote`, never recalled, never a
  promotion candidate, never in a hook block, and `wiki_export` drafts `project` memories only.
- Memories from older stores are `project`. Store maintenance (purge, revalidation, health counts, the report of
  sessions that ended without a checkpoint) and the admin API see every memory.
- **A convention, not access control:** any client can claim any id. Scope keeps cooperating agents out of each
  other's notes; it does not keep a hostile client out.

## MCP Tools

| Tool | What it does |
|------|-------------|
| `retain(content, type, session_id?, checkpoint?, source?, importance?, tags?, supersedes?, run_id?, agent_id?, task_id?, scope?)` | Store a memory. Returns `ref_id` and `supersede_suggestions`. Idempotent — the same content + type returns the same `ref_id`; content is compared in a canonical form (a byte-order mark, line endings, trailing spaces or tabs and blank lines at the ends do not count), while the text is stored as given. For a new `decision`, `convention`, `fact` or `procedure`, `supersede_suggestions` lists up to 3 live memories of that type it may replace (`ref_id`, `similarity`, `preview`; none on a repeat, or when `supersedes` is passed); pass `supersedes=<ref_id>` if one is outdated. Nothing is superseded automatically. `supersedes` hides the memory it replaces. A new memory keeps `run_id` (or `MEMKERNEL_RUN_ID`) as provenance; a matching retain keeps the original's. `scope`: `project` (default), `agent` or `task`, private to the caller's own `agent_id` or `task_id` (see [Scope](#scope-agents-and-tasks)). |
| `recall(query, type?, tier?, session_id?, checkpoint_only?, top_k?, include_needs_review?, order?, run_id?, agent_id?, task_id?)` | Search by natural language or identifier. Returns lightweight `ArtifactRef` list ranked by relevance + recency + importance. Records an access (reinforces retention). Each result carries `needs_review` and `review_reason`. Code memories flagged `needs_review` are hidden unless `include_needs_review=true`; flagged decisions are returned, marked. `run_id`, `agent_id` and `task_id` name the calling harness's run, agent and task (default: `MEMKERNEL_RUN_ID`, `MEMKERNEL_AGENT_ID`, `MEMKERNEL_TASK_ID`) for the recall log; at most 128 characters each, a longer one is refused. |
| `get(ref_id, agent_id?, task_id?)` | Fetch full content of a specific memory. Records an access. Another agent's or task's memory is not found. |
| `forget(ref_id, agent_id?, task_id?)` | Delete a memory from all indexes (not another agent's or task's: `deleted: false`). |
| `promote(ref_id, type, content?, importance?, tags?, scope?, agent_id?, task_id?)` | Turn a short-term/working memory into a long-term one (you supply the distilled text). Keeps provenance via `promoted_from` and the source's scope; `scope="project"` shares it. |
| `consolidate(session_id?, limit?, synthesize?, revalidate?, agent_id?, task_id?)` | Purge expired short-term memories and list the ones most worth promoting among the memories the caller can see (ranked by importance × how often they were recalled). `synthesize=true` also asks an external reasoner to draft long-term statements (`suggested`); `revalidate=true` first checks every code memory, and every decision with a `source`, against its file (`revalidated`). The report always carries a `health` summary. |
| `ask(ref_id, question, mode?, agent_id?, task_id?)` | Answer a question about one memory without loading it — for a `document` the full body is consulted. `mode`: `direct` \| `rag` \| `rlm` \| `auto`, passed to the reasoner unchanged; the built-in reasoner answers in `rag` mode with the best-matching chunks. Returns `answer`, `mode`, `citations`, `usage`. |
| `wiki_export(wiki_dir?)` | Compile long-term memories without a wiki page into draft markdown pages (`index.md`, `log.md` updated). |
| `wiki_import(wiki_dir?, adopt_legacy?, adopt_pages?, adopt_manifest?)` | Index wiki pages as long-term memories, each wiki keeping to its own: approved revisions only with wiki-studio ≥ 0.7.0, every page without it (idempotent; changed pages supersede; `corrects` supersedes the memories a page corrects). |

### Memory types and tiers

| Type | Tier | Use for | Default importance | Expiry |
|------|------|---------|--------------------|--------|
| `decision` | long-term | Architecture choices, library selections | 0.9 | Never (supersede instead) |
| `convention` | long-term | Naming rules, code style, project patterns | 0.9 | Never |
| `fact` | long-term | Durable project facts: build commands, environments, contracts | 0.7 | Never |
| `procedure` | long-term | How-to that worked: workflows, recipes, verified skills | 0.8 | Never |
| `code` | long-term | Function/class snapshots, API contracts; identified by `(source, content)`, a changed file supersedes the old snapshot, a drifted source flags `needs_review` | 0.6 | Never (superseded on re-retain) |
| `document` | long-term | Large artefacts (specs, transcripts, files): the body is stored and chunk-indexed, `get` returns a summary, `ask` answers from the indexed chunks (local reasoner) or the body (RLM Studio) | 0.6 | Never |
| `episode` | short-term | Session events, compaction checkpoints | 0.4 | 30 days, extended by every recall |
| `observation` | short-term | Findings, tool outputs, things noticed | 0.3 | 7 days, extended by every recall |
| `task` | working | The current goal, plan state, open questions | 0.5 | 24 hours |

Retention: `ttl = base_ttl × (1 + access_boost × access_count)`, measured from the later of creation and last access. Long-term memories never expire; a newer memory that `supersedes` an older one hides it from recall.

### Session protocol

1. **Session start** — `recall(tier="long_term", query=<task>)`, plus the latest checkpoint (`checkpoint_only=true, order="newest"`: newest first, not the most relevant). The `session-start.py` hook does this and prints promotion candidates; after a compaction it prints a shorter recovery block instead.
2. **While working** — `retain(type="task")` when the plan changes; `retain(type="observation")` for findings; durable knowledge as `decision` / `convention` / `fact` / `procedure`.
3. **Before compaction** — `retain(type="episode", checkpoint=true)` with your own summary of where the work stands; the `pre-compact.py` hook runs `consolidate()`, and the `post-compact.py` hook keeps Claude Code's compaction summary as a checkpoint.
4. **After compaction / end of phase** — `promote(ref_id, type, content)` for the candidates worth keeping.
5. **Large artefacts** — `retain(type="document", content=<body>, source=<name>)` then `ask(ref_id, question)`; never `get` a document to read it.
7. **Code snapshots** — `retain(type="code", content=<file>, source=<path>)`; retain the file again after editing it (the new snapshot supersedes the old one). The session-start hook revalidates snapshots against their files and lists the ones that need re-retaining.
6. **Curate** — `wiki_export` → review and approve the drafts in wiki-studio → `wiki_import`.

### Quick examples

```
retain(
  content="We chose PostgreSQL over SQLite because the team needs concurrent writes",
  type="decision",
  session_id="session-2024-06-01"
)

recall(query="database choice", top_k=5)

recall(query="session checkpoint", checkpoint_only=True, order="newest", top_k=1)  # the latest checkpoint

retain(content="pytest hangs unless MEMKERNEL_PROJECT_ID is set", type="observation", tags=["ci"])

consolidate()                      # -> {"purged": 0, "candidates": [{"ref_id": ..., "access_count": 3, ...}]}

promote(ref_id="<candidate>", type="fact", content="CI must export MEMKERNEL_PROJECT_ID before pytest.")

retain(content="Use arq, not Celery", type="decision", supersedes="<old decision ref_id>")

get(ref_id="<ref_id from recall>")

forget(ref_id="<ref_id>")

retain(content=<the whole spec>, type="document", source="specs/auth/spec.md")

ask(ref_id="<document ref_id>", question="Which endpoints need rate limiting?", mode="auto")
```

---

## Configuration

All settings are read from environment variables with the `MEMKERNEL_` prefix, or from a `.env` file.
Entries in `.env` without the prefix (keys for other tools) are ignored; a `MEMKERNEL_` key that matches no
setting is logged as a warning at startup.

| Variable | Default | Description |
|----------|---------|-------------|
| `MEMKERNEL_PROJECT_ID` | `default` | Project namespace — memories are isolated per project |
| `MEMKERNEL_DEFAULT_SESSION_ID` | `default` | Session tag applied when `session_id` is omitted from `retain` |
| `MEMKERNEL_CHROMA_PERSIST_PATH` | `.memkernel/chroma` | ChromaDB data directory. Empty string = in-memory (ephemeral). On POSIX systems (Linux, macOS), opening it takes a short lock on `.memkernel-open.lock` inside it, so the MCP server and a hook opening a new store at once do not collide; where `fcntl` is unavailable (Windows) the store opens without the lock, and two processes creating a new store at the same moment can still fail |
| `MEMKERNEL_CHROMA_COLLECTION_PREFIX` | `memkernel` | Prefix for ChromaDB collection names (`{prefix}_{project_id}`) |
| `MEMKERNEL_EMBEDDING_MODEL` | `all-MiniLM-L6-v2` | Sentence-transformers model name |
| `MEMKERNEL_EMBEDDING_DIMENSION` | `384` | Output dimension of the embedding model |
| `MEMKERNEL_SEARCH_TOP_K` | `5` | Default number of results returned by `recall` |
| `MEMKERNEL_RRF_K` | `60` | Reciprocal rank fusion constant (higher = flatter score distribution) |
| `MEMKERNEL_PREVIEW_LENGTH` | `200` | Max characters in the `preview` field of `ArtifactRef` |
| `MEMKERNEL_CHUNK_SIZE` | `1500` | Max characters per AST chunk (code memories) |
| `MEMKERNEL_CHUNK_OVERLAP` | `200` | Character overlap between token-based fallback chunks |
| `MEMKERNEL_DOCUMENT_STORE` | `local` | Where `document` bodies live (`local` = the project's own ChromaDB collection) |
| `MEMKERNEL_DOCUMENT_SUMMARY_CHARS` | `1000` | Characters of the body kept in a `document` memory's summary record |
| `MEMKERNEL_REASONER` | `local` | `ReasonerPort` behind `ask`: `local` (hybrid search over chunks, no LLM) or `rlmstudio` (falls back to `local` when `rlmstudio` is not importable) |
| `MEMKERNEL_ASK_TOP_K` | `5` | Chunks the local reasoner returns per `ask` |
| `MEMKERNEL_PROJECT_ROOT` | `.` | Directory that relative `source` paths of `code` memories resolve under; nothing outside it is ever read. Set it whenever the server or a hook is not started from the project directory |
| `MEMKERNEL_HEALTH_DUPLICATE_THRESHOLD` | `0.95` | Cosine similarity in [0, 1] from which two long-term memories count as near-duplicates in the health pass |
| `MEMKERNEL_SUPERSEDE_SUGGEST_THRESHOLD` | `0.61` | Cosine similarity in [0, 1] from which `retain` suggests a live memory of the same type as one the new memory may supersede. The default is calibrated for the default embedding model on 60 labelled pairs (`eval/supersede-threshold/calibrate.py`: at 0.61 it caught all 30 newer versions and suggested none of the 30 different memories; the margin is narrow, so a related but different memory can still be suggested); another embedding model needs its own calibration |
| `MEMKERNEL_HEALTH_DUPLICATE_LIMIT` | `500` | Most recent long-term memories the near-duplicate check covers |
| `MEMKERNEL_HEALTH_REPORT_LIMIT` | `20` | Items listed per category in a health report |
| `MEMKERNEL_EPISODE_TTL_DAYS` | `30` | Base TTL for `episode` memories (short-term) |
| `MEMKERNEL_OBSERVATION_TTL_DAYS` | `7` | Base TTL for `observation` memories (short-term) |
| `MEMKERNEL_TASK_TTL_HOURS` | `24` | Base TTL for `task` memories (working) |
| `MEMKERNEL_ACCESS_BOOST` | `0.5` | Each recall extends a short-term memory's TTL by this fraction of its base TTL |
| `MEMKERNEL_RECENCY_HALF_LIFE_DAYS` | `7.0` | Recency decay half-life used in recall scoring (short-term tier) |
| `MEMKERNEL_RECALL_WEIGHT_RELEVANCE` | `1.0` | Weight of hybrid-search relevance in the final recall score |
| `MEMKERNEL_RECALL_WEIGHT_RECENCY` | `0.3` | Weight of recency in the final recall score |
| `MEMKERNEL_RECALL_WEIGHT_IMPORTANCE` | `0.3` | Weight of importance in the final recall score |
| `MEMKERNEL_WIKI_DIR` | `` | Directory of the LLM wiki used by `wiki_export` / `wiki_import` (empty = pass `wiki_dir` explicitly) |
| `MEMKERNEL_STATE_DIR` | `.memkernel/state` | memkernel's own state outside ChromaDB: the wiki sync ledger. Resolved like `MEMKERNEL_CHROMA_PERSIST_PATH` (a relative path is relative to the process's working directory, so set it absolute when the persist path is); keep it out of git |
| `MEMKERNEL_RECALL_LOG` | `false` | Keep a recall log: each MCP `recall`, and each hook block that shows memories, appends one line (time, query, filters, returned `ref_id`s, and a context receipt: the run, agent and task ids; each returned memory's `content_hash` with its hashing scheme, its source and source hash, and whether it is live or flagged, never its content; the characters returned (an MCP `recall`'s whole response, or a hook's whole block); and for an MCP `recall`, its latency and how many candidates it left out as another agent's or task's, superseded, flagged, expired or over the captured-records limit, with `empty_reason` when it returned nothing; an entry names its scope when it is not `project`) to `MEMKERNEL_STATE_DIR/recall-log/<project_id>/recall.jsonl`, created readable by you only. It stores query text, so it is off by default; it stays on this computer, so keep it out of git. Nothing is written for an in-memory store. The log is locked on POSIX (Linux, macOS) only: on Windows it runs unlocked with one logged warning, and concurrent writers can lose records or pass the size limit. Used by the repeated-mistake count (see [Counting repeated mistakes](#counting-repeated-mistakes)) |
| `MEMKERNEL_RECALL_LOG_MAX_BYTES` | `5000000` | Size of one recall-log file before it is rotated to `recall.jsonl.1`, at least `4096`; a single record larger than this gives up query text first, then the per-memory receipt details (`memories_truncated`), then trailing `ref_id`s (`ref_ids_truncated`), and is marked `truncated` |
| `MEMKERNEL_RUN_ID`, `MEMKERNEL_AGENT_ID`, `MEMKERNEL_TASK_ID` | `` | The calling harness's run, agent and task ids for every call of this process, for a harness that starts one server per agent; a `recall` or `retain` argument wins. They go into the recall log, and `run_id` onto new memories. The agent and task ids also decide what the process sees and where its checkpoints go (see [Scope](#scope-agents-and-tasks)); set them for the server and the hooks alike. Caller-chosen text, not authentication: at most 128 characters each, and a longer value is ignored with a logged warning |
| `MEMKERNEL_RECALL_LOG_MAX_FILES` | `10` | Recall-log files kept, the current one included; the oldest is deleted at rotation |
| `MEMKERNEL_CAPTURE` | `false` | Capture failed-then-fixed commands from ended sessions' transcripts at the next normal startup (see [Capture](#capture-opt-in)). It reads Claude Code transcripts and stores text from them (redacted, best-effort), so it is off by default. It needs a persistent store and file locking: on Windows it stays off with one logged warning |
| `MEMKERNEL_WIKI_PROPOSALS_DIR` | `""` | Where wiki-studio patch-sets are written before promote (`memkernel[wiki]`); empty means `<project root>/.memkernel/wiki-proposals`. Setting it requests the gate: without wiki-studio installed, a warning is logged. |
| `MEMKERNEL_WIKI_MODE` | `auto` | `auto`: wiki-studio's gate and review state when wiki-studio 0.7.0 or later is installed, the direct writer and file-reading import when it is not. `governed`: `wiki_export` and `wiki_import` refuse, writing nothing, unless wiki-studio is installed with every capability memkernel uses and the wiki's manifest is `governed` (`approval_required: true`) without schema drift. `ungated`: wiki-studio is never loaded. Responses report `mode` (`gated` or `ungated`, the path that ran) and `configured_mode` (this setting). |
| `MEMKERNEL_WIKI_EXPORT_BATCH` | `10` | New pages one `wiki_export` writes at most, the most important memories first; the response's `remaining` counts the rest (`null` when the gate's outcome is uncertain or `governed` refused before reading the wiki). `0` = no limit; a negative value is refused |
| `MEMKERNEL_TRANSPORT` | `stdio` | `stdio` or `streamable-http` |
| `MEMKERNEL_HOST` | `127.0.0.1` | Host for `streamable-http` transport |
| `MEMKERNEL_PORT` | `8765` | Port for `streamable-http` transport |
| `MEMKERNEL_ALLOWED_HOSTS` | `` | Extra host names an HTTP client may use, comma-separated, beside those `MEMKERNEL_HOST` implies. Requests with any other `Host` header are refused (421), and browser requests from any other `Origin` (403). Needed when `MEMKERNEL_HOST` is `0.0.0.0` or `::`: without it, such a bind runs with no check, with a logged warning (see [Streamable HTTP](#streamable-http)) |

---

## Counting repeated mistakes

A repeated mistake is an error the agent stored in a memory that comes back in a later session. The count needs
three things: the stored memories, each session's own command output, and what memkernel showed each session.
memkernel keeps the first; Claude Code's transcripts keep the second; the recall log keeps the third.

1. **Turn the log on** before the build: `MEMKERNEL_RECALL_LOG=1` for the MCP server and the hooks (see
   [Configuration](#configuration)). Each MCP `recall`, and each hook block that shows memories, then adds one line
   to `MEMKERNEL_STATE_DIR/recall-log/<project_id>/recall.jsonl`.
2. **Run the count** after the build, from a memkernel checkout, with each store the sessions used and the
   project's transcript folder:

   ```bash
   poetry run python eval/repeat-mistakes/count.py \
     --store name=main,chroma=/path/to/.memkernel/chroma,state=/path/to/.memkernel/state,project=default \
     --transcripts ~/.claude/projects/<project folder> --json repeats.json
   ```

The rule is fixed and mechanical (it follows the one posted on #112, with the fixes from #136):
- **Stored error:** text a memory quotes in backticks that contains `Error`, `Exception`, `Traceback`, `FAILED` or
  `fatal` (case-sensitive) and more than one word. ``npm test fails with `Error: Cannot find module 'x'` `` stores
  `Error: Cannot find module 'x'`; a bare `` `ValueError` `` stores nothing. So the count needs memories that quote
  the exact error line.
- **Repeat:** a later session whose own `Bash` run **failed**, with the command's own non-zero exit code, and whose
  output contains that exact text; once per memory, session and thread. Reading a note through `cat`, `grep` or
  `git log -p` is not a repeat. Each repeat names the command. Subagent transcripts
  (`<session>/subagents/**/agent-*.jsonl`) are read too: a subagent's repeat counts toward its parent session but is
  reported on its own line, marked `(subagent)`, because a subagent gets none of the startup context. It is
  **shown** only when the subagent's own recall returned the memory, and **not shown** rather than missed otherwise.
  Errors from captured records are reported apart from the ones the agent stored.
- **Outcome**, before the failure: **shown** (memkernel returned the memory to that session), **missed** (the
  session used the memory's store, and memkernel did not return it), **other store** (the session never used that
  store), **unknown** (no log records for that session; or a miss cannot be shown, because a record of the memory's
  store whose `ref_id`s were cut (`ref_ids_truncated`), or an MCP recall that matched calls in two sessions and may have been this one's, came before
  the failure). Malformed log lines are skipped and counted. For a miss, the report says how many MCP recalls and hook
  blocks came before the failure, and whether every MCP recall's type, tier, session or checkpoint filter excluded the memory. It also counts the
  later sessions (each once) that were shown a memory and did not repeat its error.
- **By run and agent:** when the log records of a repeat's session carry a harness `run_id` or `agent_id`
  (`MEMKERNEL_RUN_ID`, `MEMKERNEL_AGENT_ID`, or the `recall` arguments), the report adds the same outcome counts per
  run and per agent (`by_run`, `by_agent`; `several` when one session's records name more than one). Without ids
  the report is as before.

**Check the report before sharing it.** It quotes each matched error text, which is text from your memories and
from the sessions' command output in the transcripts, together with memory ids and session ids. The `--json` file
holds the same.

What it cannot detect:
- a reworded or differently quoted error (exact text only);
- a lesson written in prose with no quoted error, or quoted as a single word such as `` `ValueError` ``; a
  multi-word code fragment such as `` `except Exception:` `` still counts as a stored error;
- output that is not from a failed run: an error printed by a command that exits 0, or a note read through `Bash`;
- above all, a command piped into a filter without `set -o pipefail`, such as `… 2>&1 | tail -20`: its real failure
  exits 0, so it is not counted;
- a failure seen through a tool other than `Bash`;
- sessions whose recalls were not logged: the log was off, or an MCP recall matched calls in two sessions and was
  not guessed;
- recalls made through the Python library rather than the MCP tool or a hook;
- whether a memory was flagged for review when a recall ran: a recall that hid flagged memories may have hidden it;
- tools other than Claude Code: only its transcripts are read (#107).

## Transports

### stdio (default)

Used by Claude Code and most MCP clients. The client spawns the server as a subprocess.

```bash
memkernel           # stdio, uses defaults
```

### Streamable HTTP

For persistent server processes or multi-client setups:

```bash
MEMKERNEL_TRANSPORT=streamable-http memkernel
```

The server listens at `http://127.0.0.1:8765/mcp` by default.

**Local only, no authentication.** Any process on the machine can read and write the store through this port. A
request whose `Host` header names another host is refused, so a web page can't reach the server through DNS
rebinding; so is a browser request from another origin.
- **Loopback** (`127.0.0.1`, the default): the loopback names are allowed.
- **A specific address:** that address is allowed, with a logged warning that there's no authentication.
- **`0.0.0.0` or `::`:** the loopback names plus the names clients use, listed in `MEMKERNEL_ALLOWED_HOSTS`.
  Without that setting, the server runs with no check, with a warning; don't expose it to a network you don't trust.

---

## Using memkernel from a harness

A harness that runs several agents or tasks against one store can tell memkernel who is calling, keep each agent's
notes apart, record what each run received, and later compare that with the store. memkernel owns memory, retrieval,
provenance and its own measurements; orchestration and tracing stay the harness's (#119).

1. **Name the caller.** Pass `run_id`, `agent_id` and `task_id` to `recall` and `retain` (and `agent_id`/`task_id` to
   `get`, `ask`, `forget`, `promote`, `consolidate`), or set `MEMKERNEL_RUN_ID`, `MEMKERNEL_AGENT_ID` and
   `MEMKERNEL_TASK_ID` for a server started per agent; a call's value wins. At most 128 characters each. Set the agent
   and task ids for the hooks as well: they read only their own environment, and recover checkpoints from that scope.
   A new memory keeps `run_id` as provenance.
2. **Keep private notes private.** `retain(..., scope="agent")` or `scope="task"` makes a memory visible only to that
   agent or task; everything else is shared `project` knowledge. Checkpoints go to the caller's task, else agent, else
   `project`; `scope="project"` hands work to anyone, and `promote(..., scope="project")` publishes a private note.
   See [Scope](#scope-agents-and-tasks).
3. **Record what each run received.** With `MEMKERNEL_RECALL_LOG=1`, every `recall` and every hook block writes a
   receipt to the recall log: the run, agent and task ids; per returned memory its `content_hash` and hashing scheme,
   source, source hash, state and (when private) scope, never its content; the characters returned; and for an MCP
   `recall` its latency, the candidates it left out (`out_of_scope`, `superseded`, `flagged`, `expired`, `capped`),
   and `empty_reason` when it returned nothing.
4. **Compare a run with the store now.** From a clone of this repository:

   ```bash
   poetry run python eval/context-diff/diff.py \
       --store chroma=.memkernel/chroma,state=.memkernel/state,project=my-project,root=/path/to/project \
       --run <run_id> --json context-diff.json
   ```

   Each memory the run received is `unchanged`, or `missing`, `superseded` (and by what), `withdrawn`, `changed`,
   `rehashed`, `flagged`, `source changed` or `unknown`, several at once where they apply. Without `root=` it makes
   no source checks and says so. It exits 0 with a report, 1 when no log record carries the run id, 2 when the store
   cannot be opened or read.
5. **Measure repeated mistakes per run and agent.** [The count](#counting-repeated-mistakes) groups its report by
   `run_id` and `agent_id` when the log has them.

Limits:
- **Scope is a convention, not access control:** any client can claim any id.
- **Receipts need the recall log,** which stores query text, so it is off by default and stays on this computer. A
  record over `MEMKERNEL_RECALL_LOG_MAX_BYTES` gives up query text, then per-memory details, then `ref_id`s; the diff
  reports a memory it has no hash for as `unknown`.
- **The diff's source check** compares whole files, for decisions and code, through their `source` only: a changed
  file does not mean the memory is wrong, and files the memory's text cites are not checked.
- **Why a memory was selected** is only what the receipt records (the query, its filters, the exclusions); no
  per-memory score or reason is kept.
- **No OpenTelemetry:** the ids in the log are what a harness's own tracing joins on.
- **The diff and the count are repository tools** (`eval/`), not part of the installed package.

## Embedding MemKernel in your own harness

```python
from memkernel.factory import build_service
from memkernel.core.models import MemoryType

svc = build_service()                      # settings from MEMKERNEL_* env vars
svc.retain("Use Postgres", MemoryType.DECISION)
for ref in svc.recall("database"):
    print(ref.tier, ref.score, ref.preview)
report = svc.consolidate()                 # {"purged": n, "candidates": [...]}
```

`build_service()` is the supported entry point; the MCP server, the admin API and the hook templates all use it. If you pass a `PersistentClient` as `chroma_client` and also set `MEMKERNEL_CHROMA_PERSIST_PATH` (in the environment or in the settings), both must name the same directory, or `ValueError` is raised; with the default setting, the client's own directory is used.

**Run one memkernel version per store.** Records now state the scheme of their content hash (`hash_scheme`; records written by memkernel 0.9.0 and earlier are `sha256-raw`, new ones `sha256-canonical-v1`, which hashes a canonical form of the text). A memkernel 0.9.0 or earlier sharing the store (a server, a hook, another tool's server) ignores the scheme: it stores a second copy of a text a newer process stored, and its revalidation flags newer code memories and decisions as `changed`. Upgrade every process that shares a store together.

**Store locks.** Processes that share a store (the MCP server, a hook, a script) coordinate through locks keyed by the store itself: lock files in the persist directory, `.memkernel-<name>-<key>.lock`, whatever each process's `MEMKERNEL_STATE_DIR` is; an in-memory store's locks are per process. Only one writer changes a record's tags, under the store's `tags` lock, so a tag added by one process is never dropped by another's write. Locks are not re-entrant (taking one the thread already holds raises `LockReentryError`), a wait longer than 10 seconds is logged once, and spelling the persist directory with different letter case in two processes gives two locks, so use one spelling. The locks use `fcntl` and are verified on POSIX (Linux, macOS) only; on Windows they run unlocked across processes, with one logged warning per lock. Integration notes for `code-copilot-team` and `haa` are in [`docs/integration/harness-integration.md`](docs/integration/harness-integration.md).

### The session protocol as a component

`MemoryLifecycle` packages what the hook scripts do, so a harness calls five methods instead of re-implementing the protocol. Every method returns markdown ready for injection and does nothing but talk to the service:

```python
from memkernel.factory import build_service
from memkernel.lifecycle import MemoryLifecycle

memory = MemoryLifecycle(build_service())
system_context = memory.on_session_start()       # checkpoint, long-term context, promotion candidates, wiki pointer
...
memory.on_pre_compact(summary)                   # checkpoint episode (only if summary is not blank) + consolidation
recovered = memory.on_post_compact()             # what to re-inject after your own compaction
                                                 # (context chosen by the latest checkpoint, as compaction recovery does)
memory.on_session_end(summary)                   # final checkpoint + consolidation

# Driving it from Claude Code's hook events instead (what templates/hooks/ do):
memory.on_session_start(source)                  # source "startup"/"clear": full block; "compact": recovery block; "resume"/"fork": ""
memory.capture_compact_summary(compact_summary, session_id=..., trigger=...)  # keep Claude Code's own summary as a checkpoint
```

### Documents and `ask`

`retain(type="document")` keeps large artefacts out of the context window: the body goes to the document store (built-in: the project's own ChromaDB collection), its chunks are indexed for hybrid search, and the memkernel record is a summary. `ask(ref_id, question, mode)` answers through a `ReasonerPort`:

- `MEMKERNEL_REASONER=local` (default) — no LLM: the question is matched against the document's chunks with dense + BM25 + RRF and the best chunks come back as the answer, `mode="rag"`.
- `MEMKERNEL_REASONER=rlmstudio` — delegates to [rlm-studio](https://github.com/gosha70/rlm-studio)'s `interact(content, question, mode=mode)`, so `direct`, `rag`, `rlm` and `auto` select how the document is read (ADR-009). `rlm-studio` is not a memkernel dependency and is not on PyPI yet; install it from git into the same environment:

  ```bash
  pip install "rlm-studio @ git+https://github.com/gosha70/rlm-studio"
  ```

  When it is not importable, `build_service()` logs a warning and uses the local reasoner. With an external reasoner, `consolidate(synthesize=True)` also drafts long-term statements from the session's short-term memories.

## LLM wiki bridge

Long-term memory has a human-readable twin: a markdown wiki in the [LLM Wiki](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) pattern (`index.md`, `log.md`, typed pages with cited sources — the same schema as `code-copilot-team/knowledge/wiki`).

To see the whole loop on a clean install, follow wiki-studio's [memkernel composition quickstart](https://github.com/gosha70/wiki-studio/blob/main/docs/quickstart-memkernel.md): retain a memory, export it through wiki-studio's gate, correct and approve the page, import only the approved revision, and see the next `recall` return it. CI runs the quickstart against memkernel **0.6.0**.

- `wiki_export` compiles every long-term memory that has no page yet into a **draft** page under `decisions/`, `concepts/` or `workflows/`, with the required sections and a `memkernel://<project>/<ref_id>` citation. Existing pages are never overwritten.
- `wiki_import` indexes pages as long-term memories so `recall` finds the reviewed version; a changed page supersedes its earlier memory. With wiki-studio 0.7.0 or later installed it is **governed** (`"governed": true`): it imports only pages wiki-studio's review state reports approved, and only when the page's bytes are still the approved revision, so drafts, self-declared approvals and pages edited after approval are not imported (`not_approved` says why); an edited page keeps its last approved memory until it is approved again. memkernel never approves a page; a curator does, with `wiki-studio approve`. Without wiki-studio the import reads the page files, drafts included, and reports `"governed": false`. An installed wiki-studio that is broken or older than 0.7.0 imports nothing and reports `import_error`.
- **Withdrawal (governed import, 0.7).** A page's memory leaves the current answers, its record kept for history, when:
  - the page is **deleted**. Only memories this wiki's sync ledger recorded as imported are withdrawn this way; a memory imported before 0.7, or without wiki-studio, never is.
  - the page is **deprecated**, once the `status: deprecated` revision is approved.
  - the page is **superseded** (`superseded_by: <page path>`). Its memory is replaced by the successor page's memory; if the successor has none yet, the old memory is withdrawn and linked once it does (`pending` until then).

  The response lists `withdrawn`, `superseded`, `pending` and `sync_failed` (retried at the next import). The ledger is one JSON file per project and wiki under `MEMKERNEL_STATE_DIR/wiki-sync/`; a corrupt one is kept aside, reported as `ledger_error`, and rebuilt.
- **Corrections.** An approved page can name the memories it corrects in its frontmatter: `corrects: <ref_id>, <ref_id>` (one line; tokens of letters, digits, `-` and `_`). On import each named memory that did not come from the wiki is superseded by the page's memory: it stops being a current answer, and its record is kept. References that cannot be applied are listed in `unresolved` with a reason (unknown, another project's, already superseded, or a wiki memory: correct that page instead); a value that breaks the grammar is listed in `invalid_corrects`, and the page is still imported. An approved page that is already current is listed in `unchanged`, and its corrections are reconciled again on every import, so a reference that could not be applied earlier takes effect once it can; corrections already applied are not repeated.

- **Each wiki keeps to its own memories (0.7).** Every memory `wiki_import` writes, or finds current, carries its wiki's identity: `wiki-path:<hash>` (the wiki directory's path relative to the project root) and, when the wiki has a wiki-studio manifest, `wiki-id:<uuid>`. A page's previous memory, its corrections, its supersession and its deprecation are only that wiki's, so two wikis in one store may share page paths and `page_id`s. These tags are reserved: `retain` refuses them, and an ordinary `retain` whose text matches a wiki memory gets its own record instead of merging into it; `promote` drops every wiki tag from its copy.
  - **A wiki that may move, or that shares a store with another wiki, needs a manifest.** The path a wiki is known by is relative to its project root: two project roots sharing one store, with wikis at the same relative path, get the same `wiki-path:`, so the second import is refused (memories at this path belong to another wiki) even with manifests. Use one store per project, or different relative paths. Without one, a wiki *is* its path: moved, it starts afresh, and whatever wiki is later placed at the old path continues its memories. A copied wiki directory (two directories, one `wiki_id`) is one wiki: each import moves its memories to the directory imported last.
  - **Upgrading a 0.6 store:** memories written before 0.7 carry no identity, so the first import writes nothing for their pages and lists them under `ambiguous` (`{"path", "ref_ids", "reason"}`). Import once with `adopt_legacy=true` to adopt each page's sole such memory; a page with several stays `ambiguous` (forget the ones that are not its own). With several wikis in one store, name the records instead: `adopt_pages=[{"path", "ref_id"}, …]` copied from `ambiguous`; a named record that changed meanwhile is not adopted (`candidate changed`).
  - **Identity changes stop the import before any write, with the remedy:** a wiki that gained a manifest needs `adopt_manifest=true` once (its sync ledger moves to the `wiki_id` key; if both ledger files exist, delete the stale one); memories at this path that belong to another `wiki_id` (the manifest removed or replaced, or a moved wiki not yet imported from its new place) stop it until the manifest is restored, the moved wiki is imported first, or those memories are forgotten. A wiki with a manifest that moves keeps its memories; the next import moves their path.
  - One import runs at a time per store (the `wiki-import` store lock). On Windows the import runs unlocked with one warning, as in 0.6: two concurrent imports of one wiki can leave two records for a page (the next import reports it as `duplicate records`; forget one), and two wikis adopting the same record at once can tag it for one while the other supersedes it. Give processes that share a store the same `MEMKERNEL_STATE_DIR`, so they share the sync ledger.
Set `MEMKERNEL_WIKI_DIR` (for example `knowledge/wiki`) or pass `wiki_dir` to the tools. The standalone maintainer that owns this page schema is [wiki-studio](https://github.com/gosha70/wiki-studio). With the `memkernel[wiki]` extra installed, every `wiki_export` response carries wiki-studio's lint and health findings for the whole wiki after the export, curated pages included, under `lint` (`violations`, `audit_errors`, `pages_checked`, `health` items with `kind`, `severity`, `pages`, `description`); without it `lint` is `null` and `lint_hint` says how to enable it; if the lint pass itself fails, `lint` is `null` and `lint_error` says why. The files written are the same in every case.

With wiki-studio 0.7.0 or later installed, `wiki_export` writes through wiki-studio's promote gate: wiki-studio's `init` creates `index.md` and `log.md` if they are missing (wiki-studio's own scaffold, `status: stable`), then every new page goes with its index and log lines into one patch-set that is proposed and promoted. Other writers can work in the same wiki: wiki-studio's commit writes only the paths the patch-set names, under its lock, and refuses a page someone else created in the meantime. A rejected export writes no page and the response carries `gate_error` (a new wiki keeps the `index.md` and `log.md` that `init` created); so does an installed wiki-studio that is broken or older than 0.7.0, rather than falling back to the direct writer. A promoted export's response adds `proposal`, `submission_digest` and `archived_dir` from wiki-studio's receipt. If `archived_dir` is `null`, the pages landed but wiki-studio did not finish: it could not archive the proposal, or it failed after committing the pages (memkernel checks wiki-studio's receipt: while it still says `committing`, every planned write, index and log included, must be at its post-write sha256; a `committed` receipt needs memkernel's pages at theirs; an unusable receipt falls back to comparing the pages' bytes). `archive_hint` gives the `promote` command that tries to finish it, with absolute paths, so it runs from any directory. It applies nothing twice, but if the wiki or the proposal changed since, for example another writer appended to `index.md`, it may refuse with `uncertain_outcome` or `payload_changed` and write nothing; then compare the wiki with the proposal's `receipt.json` by hand. memkernel never runs it itself. If wiki-studio failed during its commit and its receipt shows neither a commit nor a rollback (say the page was written, the `index.md` write failed and removing the page failed too), the response carries `gate_error` with `uncertain_outcome` and `proposal`: `written` is empty, but the pages it names may be on disk; compare the wiki with the `receipt.json` it names before exporting again. `receipt_error` says the receipt could not be read or used. A failed export leaves its patch-set under the proposals directory for inspection; delete it once the cause is fixed. Patch-sets go to `MEMKERNEL_WIKI_PROPOSALS_DIR`, by default `.memkernel/wiki-proposals/` under the project root. Commit `<wiki>/.audit/`, wiki-studio's audit trail of promoted proposals; ignore `.memkernel/wiki-proposals/`, `.memkernel/state/` (memkernel's sync ledger) and wiki-studio's files next to the wiki directory, `.<wiki-dir>.wiki-studio.*` (for `knowledge/wiki`, `knowledge/.wiki.wiki-studio.*`: its lock file and, from wiki-studio 0.8, its search cache).

**Wiki modes.** `MEMKERNEL_WIKI_MODE` is a property of the deployment, not of a call. `governed` runs one preflight before any page is written or read, for export and import alike: wiki-studio 0.7.0 or later installed and working; its `info` listing the capabilities `wiki-lock`, `receipts`, `root-manifest`, `page-id`, `approval-record`, `superseded-by` and `findings`; the wiki's manifest mode `governed`; no schema drift. A `managed` or `legacy` wiki is refused with the remedy: run `wiki-studio init` if there is no manifest, then set `approval_required: true` in the manifest's policy. A refusal reports `gate_error` (export) or `import_error` (import) and writes nothing; `update_index=False` is refused too, since the direct writer is never used. A gate rejection after the preflight commits no drafted page, but a new wiki keeps the `index.md` and `log.md` that wiki-studio's `init` created: memkernel keeps no outer rollback. `ungated` never loads wiki-studio (no gate, lint, review state or findings): `lint` is `null` and `lint_hint` names the mode.

**Export batches and grounding.** One `wiki_export` writes at most `MEMKERNEL_WIKI_EXPORT_BATCH` new pages (by importance, highest first, then oldest, then `ref_id`), so a curator reviews a small batch at a time; `remaining` counts the eligible memories still without a page, all of them after a rejected batch. Every exported page carries `memkernel_sha256`, the memory's content hash, beside `memkernel_ref`; a `path:` source gains `sha:`, the commit it is grounded at (`git log -1 --format=%h`, wiki-studio's citation rule), only when the project's `git ls-files` lists exactly that file and `git status` shows no change to it: a modified, staged or untracked file, a file in a submodule, or no git gets none. Pages created through the gate carry wiki-studio's `page_id`, so a page renamed or moved under its `page_id` keeps its memory: the next import supersedes the memory at the old path with one at the new path, also when the moved page's bytes are unchanged.

**Curation debt at session start.** With `MEMKERNEL_WIKI_DIR` set and wiki-studio available (in `governed`, only after the preflight passes), the session-start block (`startup`, `clear`) gains `### Curation debt`: one line of wiki-studio's `findings` counts in a fixed order (review kinds first) plus the sync ledger's unfinished actions (`sync pending`, `sync failed`), up to three example pages, and a hint to run `wiki-studio findings`. It uses at most 500 characters, taken from the long-term context's share, so the block stays under 9,000 characters. The check runs in a child process bounded to 2.5 seconds once it has started (a fork or exec the operating system holds up is not covered); it reads the sync ledger without changing it and never waits for an import that holds it. Any failure is one `Curation debt unavailable: <reason>` line. Not on `compact`, `resume` or `fork`, nor in `ungated`.

**wiki-studio's files beside the wiki, its ingest log, and wiki-studio 0.8.** When memkernel exports through the gate, wiki-studio creates its lock file, `.<wiki-dir>.wiki-studio.lock`, beside the wiki directory, and from 0.8 a curator's `find` or `query` adds a search cache, `.<wiki-dir>.wiki-studio.search.sqlite`, there too: for a wiki kept in git, ignore both with `.<wiki-dir>.wiki-studio.*` (for `knowledge/wiki`, `knowledge/.wiki.wiki-studio.*`). memkernel creates no file of its own there. memkernel reads no wiki-studio ingest log, so the log's `hash_recipe` has no consumer in memkernel. From wiki-studio 0.8.0 a page that is not valid UTF-8 fails lint for the whole wiki, so every promote, memkernel's gated export included, is refused with a `gate_error` naming that page until it is re-encoded or removed. From 0.8.0 an unknown `WIKI_STUDIO_RANKER` value makes wiki-studio's `info` fail, so a `governed` export or import, a gated import and the curation debt refuse with wiki-studio's message naming the variable. memkernel needs wiki-studio 0.7.0 or later and is tested at 0.7.0; an informational CI job runs the wiki tests against the newest release below 1.0 on every pull request and weekly.

wiki-studio's MCP server (`wiki-studio-mcp`, from wiki-studio 0.8.0) needs `mcp>=2.3`, as memkernel does from 0.9 ([ADR-011](docs/adr/ADR-011-mcp-2.md)), so both install into one environment: `pip install 'memkernel[wiki]' 'wiki-studio[mcp]>=0.8,<1'`. Register `wiki-studio-mcp` beside memkernel's server.

memkernel 0.8 and earlier need `mcp<2`, so there wiki-studio's server runs in its own environment, at the same wiki-studio version as memkernel's:

1. In memkernel's environment, read the version: `python -c "import importlib.metadata as m; print(m.version('wiki-studio'))"`. If it is below 0.8.0, upgrade it there first: `pip install 'wiki-studio>=0.8,<1'`.
2. Install exactly that version for the server, for example `pipx install 'wiki-studio[mcp]==0.8.1'`, and register it beside memkernel's server.

On one machine and one filesystem, wiki-studio's lock serializes the two servers' writes to the same wiki. It does not coordinate other hosts, and network filesystems are outside its scope.

Rationale: [`docs/adr/ADR-008-llm-wiki-as-semantic-layer.md`](docs/adr/ADR-008-llm-wiki-as-semantic-layer.md) and [`docs/adr/ADR-010-wiki-studio-as-wiki-maintainer.md`](docs/adr/ADR-010-wiki-studio-as-wiki-maintainer.md).

### Revalidation and store health

A `code` memory is a snapshot of a file. `MemoryService.revalidate()` hashes each live snapshot's whole source file and compares it with the stored content hash: a changed file flags the memory `needs_review` (`changed`), a vanished file flags it `missing`, a matching file clears the flag. Flagged memories leave default `recall` until the file is retained again (which supersedes the stale snapshot) or they are asked for with `include_needs_review=true`. Revalidation runs from `consolidate(revalidate=true)`, at every session start through `MemoryLifecycle.on_session_start()` (a `### Needs review` section lists what to re-retain), and from `POST /revalidate`. Sources resolve under `MEMKERNEL_PROJECT_ROOT` (default: the current directory); set it whenever the server or a hook is not started from the project directory. Nothing outside that root is ever read. 0.4 hashes whole files; per-chunk invalidation is a follow-up.

A `decision` that cites a file in `source` is revalidated too. When a decision is created, memkernel records the hash of that file (if it is a readable file under the project root) as `source_hash`; a retain that matches an existing decision returns it unchanged, with its own source and hash. Revalidation flags the decision `changed` when the file's hash differs and `missing` when the file is gone; a decision saved before 0.9.0, without a hash, is flagged only when its file is missing, and a present file clears only that flag. **A flagged decision is not hidden:** `recall` returns it with `needs_review: true` and its `review_reason`, so the agent re-checks the evidence instead of losing the decision (a file edit unrelated to the decision flags it too). It is listed under `### Needs review` at session start, marked `[decision]`; the list shows every memory still flagged, including one whose file could not be read this time. Only `source` is checked, not other paths the decision cites. Records the wiki import manages (they carry a `wiki-path:` or `wiki-id:` tag) are not revalidated: their `source` is a page path inside the wiki, and the import keeps them current; a record imported by memkernel 0.6 gets that tag when adopted with `wiki_import(adopt_legacy=true)`.

`MemoryService.health()` audits the store without changing it: orphaned chunk and document records, dangling `supersedes` / `superseded_by` / `promoted_from` / `parent_ref` links, supersessions from 0.2/0.3 that lack the durable marker, `code` memories whose source file is gone, memories flagged for review, expired short-term memories not yet purged and, in full mode only, near-duplicate pairs among the most recent long-term memories (cosine ≥ `MEMKERNEL_HEALTH_DUPLICATE_THRESHOLD`). The quick report (counts only, no embeddings, no content loads) is part of every `consolidate()` report and of the `memory://status` resource; the full report is `GET /health/store`. The pass never fixes anything: a fix mode is a later feature.

## Admin API

A FastAPI admin server provides health and stats endpoints (independent of MCP):

```bash
uvicorn memkernel.api.app:app --host 127.0.0.1 --port 8766
```

| Endpoint | Description |
|----------|-------------|
| `GET /health` | Server health and memory count |
| `GET /stats` | Total memory count, per-type and per-tier breakdown, growth rate, last recall latency |
| `GET /collections` | List ChromaDB collections |
| `GET /health/store` | Full store health report (orphans, dangling links, stale sources, near-duplicates, …) |
| `POST /revalidate` | Check every code memory, and every decision with a `source`, against its file; flag changed or missing ones |

---

## Development

```bash
git clone https://github.com/gosha70/memkernel
cd memkernel
poetry install
poetry run pytest --tb=short -q          # full test suite
poetry run pytest -m "not slow" -q       # skip slow tests
ruff check . && mypy src/                # lint + type check
```

CI runs on every push and PR: lint, type check, tests (≥ 80% coverage), security scan, and build verification.

### Releasing

Releases are published to PyPI by [`.github/workflows/release.yml`](.github/workflows/release.yml) using trusted publishing (no token in the repo). To cut a release:

1. Set `version` in `pyproject.toml` and `__version__` in `src/memkernel/__init__.py` to `X.Y.Z`, and move the `[Unreleased]` entries in [`CHANGELOG.md`](CHANGELOG.md) under `[X.Y.Z] - <tag date>`.
2. Merge to `main` with CI green.
3. Tag and push: `git tag -a vX.Y.Z -m "memkernel X.Y.Z" && git push origin vX.Y.Z`.
4. Create the GitHub Release from the tag, with the version's CHANGELOG section as its notes:

   ```bash
   awk -v v=X.Y.Z 'index($0, "## [" v "]") == 1 {f=1; next} f && /^## \[/ {exit} f' CHANGELOG.md > release-notes.md
   gh release create vX.Y.Z --title X.Y.Z --notes-file release-notes.md --verify-tag
   ```

The workflow refuses a tag that does not match the `pyproject.toml` version, builds the sdist and wheel, smoke-installs the wheel, and uploads through the `pypi` environment.

---

## Architecture

```
src/memkernel/
├── mcp/           # MCP server + tool definitions (memory tools, wiki tools)
├── core/          # Domain models (tiers, types), MemoryService, ports (interfaces)
├── adapters/      # Optional external systems (RLM Studio reasoner), imported lazily
├── storage/       # ChromaDB adapter, local document store
├── retrieval/     # AST/token chunking, embeddings, hybrid search (dense + BM25 + RRF + rescoring), local reasoner
├── memory/        # Lifecycle: TTL/decay policies, retention, deduplication
├── wiki/          # LLM-wiki bridge: page model, export, import
├── api/           # FastAPI admin endpoints
├── factory.py     # build_service() — the supported embedding entry point
├── lifecycle.py   # MemoryLifecycle — the session protocol as a component
└── config.py      # Pydantic settings
```

Ports-and-adapters design: `core/` depends only on protocols in `core/ports.py`, never on concrete backends. Storage and embedding backends are swappable.

Further reading: [`docs/architecture/memory-tiers.md`](docs/architecture/memory-tiers.md) (design), [`docs/research/memory-literature-review.md`](docs/research/memory-literature-review.md) (HRM, JEPA, MemGPT, Mem0, Zep, HippoRAG, Generative Agents, Titans, …), [`docs/research/sibling-projects.md`](docs/research/sibling-projects.md) (what is shared with rlm-studio, document-assistant, ragkit, code-copilot-team, haa), [`docs/adr/`](docs/adr/), [`docs/roadmap.md`](docs/roadmap.md).

---

## Related projects

MemKernel is the memory component of a small family of projects by the same author; each is usable on its own.

| Project | Role | Relationship |
|---|---|---|
| [wiki-studio](https://github.com/gosha70/wiki-studio) | LLM-wiki maintainer (ingest / promote / query / lint / audit), stdlib-only | the human-readable form of long-term memory; `wiki_export` / `wiki_import` speak its page schema (ADR-008), and CI lints exporter output with it |
| [rlm-studio](https://github.com/gosha70/rlm-studio) | Recursive Language Models workbench: Direct / RAG / RLM / auto over large documents | the document layer behind `document` memories and the `ask()` tool (`MEMKERNEL_REASONER=rlmstudio`, ADR-009) |
| [code-copilot-team](https://github.com/gosha70/code-copilot-team) | Enforceable harness configuration for Claude Code, Pi and other copilots | consumes MemKernel through MCP and hooks |
| [haa](https://github.com/gosha70/haa) | Home-built AI coding harness, future component assembler | consumes MemKernel in-process through `build_service()` |

The cross-repository sequence is in [`docs/roadmap.md`](docs/roadmap.md).

## License

Apache-2.0. See [`LICENSE`](LICENSE) and [`NOTICE`](NOTICE). Changes are tracked in [`CHANGELOG.md`](CHANGELOG.md).

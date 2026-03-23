# MemKernel — Claude Code Memory Instructions

Copy the relevant sections below into your project's `CLAUDE.md` to give Claude Code
persistent memory across sessions via MemKernel.

---

## Minimal setup (paste into CLAUDE.md)

```markdown
## Memory

This project uses MemKernel for persistent memory across sessions.
MCP server: memkernel (configured in .claude/settings.json)

### Storing memories
Call `retain` for anything worth keeping:
- Architectural decisions → type=decision
- Coding conventions → type=convention
- Code snapshots → type=code, source=<file path>
- Session events → type=episode

### Recalling memories
Call `recall` at the start of a new session or after compaction:
  recall(query="recent decisions and context")

### Pre-compaction checklist
Before context is compacted, call retain with checkpoint=true:
  retain(
    content="SESSION CHECKPOINT\nDecisions: ...\nConventions: ...\nNext steps: ...",
    type=episode,
    checkpoint=true
  )

### Post-compaction recovery
After compaction, recover context with:
  recall(query="session checkpoint", checkpoint_only=true)
  recall(query="key decisions and conventions")
```

---

## Full instructions (detailed)

### What MemKernel stores

| Type | When to use | Expiry |
|------|-------------|--------|
| `decision` | Architectural choices, library selections, approach decisions | Never |
| `convention` | Project-specific rules, naming patterns, style choices | Never |
| `code` | Function/class snapshots, API contracts, schema definitions | Never |
| `episode` | Session events, tool outputs, compaction checkpoints | 30 days (default) |

### Retaining memories

```
retain(content=<text>, type=<type>, session_id=<optional>, source=<optional file path>)
```

- `content`: The memory text. Be specific — vague memories are hard to retrieve.
- `type`: One of `decision`, `convention`, `code`, `episode`.
- `session_id`: Tag memories by session for later filtering (optional).
- `source`: File path or tool name for provenance (optional, required for `code` type).
- Returns: `ref_id` — keep this if you plan to `get` or `forget` later.

Retain is idempotent: identical content + type within a project returns the same
`ref_id` and updates the timestamp/session_id. Safe to call multiple times.

### Recalling memories

```
recall(query=<text>, type=<optional>, session_id=<optional>, checkpoint_only=<bool>, top_k=<int>)
```

Returns a list of `ArtifactRef` (ref_id, preview, score, token_count, type, timestamp).
Use `get(ref_id)` to retrieve full content for a specific memory.

### Pre-compaction workflow

When you detect that context is approaching the limit — or when the user says
"compact" — execute this sequence **before** compaction:

1. Summarise the current session into a structured checkpoint:

```
retain(
  content="""SESSION CHECKPOINT — <date>
Decisions made this session:
- <decision 1>
- <decision 2>

Conventions established:
- <convention>

Current task: <what was in progress>
Next steps: <what to do after recovery>
Open questions: <any unresolved items>
""",
  type=episode,
  checkpoint=true,
  session_id=<current session id>
)
```

2. Retain any important code snapshots or decisions that came up during the session.

### Post-compaction recovery

At the start of a new session (or after compaction), recover context with two calls:

```
# 1. Get the most recent checkpoint (structured summary of last session)
recall(query="session checkpoint recent decisions next steps", checkpoint_only=true, top_k=3)

# 2. Broaden recall to surface relevant long-term context
recall(query="<current task or topic>", top_k=10)
```

Combine the results to reconstruct working context before continuing.

### Hook setup (automated)

See `templates/hooks/` for Python scripts that automate the pre/post-compaction
workflow via Claude Code hooks. Copy them to `.claude/hooks/` and register in
`.claude/settings.json` (see the Prerequisites section in each script for the
Python environment requirement).

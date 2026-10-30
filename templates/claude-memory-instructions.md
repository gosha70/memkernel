# MemKernel — Claude Code Memory Instructions

Copy the relevant sections below into your project's `CLAUDE.md` to give Claude Code
persistent, tiered memory across sessions via MemKernel.

---

## Minimal setup (paste into CLAUDE.md)

```markdown
## Memory

This project uses MemKernel for persistent memory across sessions.
MCP server: memkernel (configured in .claude/settings.json)

Memory has three tiers. Pick the type; the tier follows.
- long-term (never expires, supersede to replace): decision, convention, fact, procedure, code, document
- short-term (decays unless recalled): episode, observation
- working (expires in ~24h): task

### Session start
(Skip this when the memkernel hooks are installed: the SessionStart hook already injects it.)
  recall(query="<current task>", tier="long_term", top_k=8)
  recall(query="session checkpoint", checkpoint_only=true, order="newest", top_k=1)
Read the wiki index first if the project has one (MEMKERNEL_WIKI_DIR/index.md).

### While working
- Plan changed or sub-task started → retain(type="task", content="Goal: … Next: … Open: …")
- Found something (test output, a quirk, a measurement) → retain(type="observation", content=…, tags=[…])
- Learned something true beyond this session → retain(type="fact"|"decision"|"convention"|"procedure")
- A decision replaced an older one → retain(type="decision", supersedes="<old ref_id>")
- Edited a file you had retained as code → retain(type="code", content=<new file>, source=<same path>) (supersedes the old snapshot)
- Anything longer than a screen (a spec, a transcript, a file) → retain(type="document", content=<body>, source=<name>)
  then ask(ref_id=…, question=…) instead of get() — get() only returns the summary

### Before compaction
  retain(content="SESSION CHECKPOINT\nDone: …\nCurrent: …\nNext: …\nOpen: …",
         type="episode", checkpoint=true)
  consolidate()

### After compaction / end of a phase
  consolidate()  → for each candidate worth keeping:
  promote(ref_id=…, type="fact"|"decision"|"procedure", content="<distilled, one idea>")

### Curating knowledge
  wiki_export()  → review the draft pages → wiki_import()
```

---

## Full instructions (detailed)

### What MemKernel stores

| Type | Tier | When to use | Expiry |
|------|------|-------------|--------|
| `decision` | long-term | Architectural choices, library selections, approach decisions | Never — `supersedes` an older decision instead |
| `convention` | long-term | Project-specific rules, naming patterns, style choices | Never |
| `fact` | long-term | Durable facts: build commands, environment quirks, contracts, measured results | Never |
| `procedure` | long-term | A workflow or recipe that worked and was verified | Never |
| `code` | long-term | Function/class snapshots, API contracts, schema definitions; one live snapshot per path | Never (superseded on re-retain; flagged `needs_review` when the file drifts) |
| `document` | long-term | Large artefacts (specs, transcripts, files): body stored and chunk-indexed, `get` returns a summary | Never |
| `episode` | short-term | Session events, compaction checkpoints | 30 days, extended by every recall |
| `observation` | short-term | Findings and tool outputs worth keeping for a few days | 7 days, extended by every recall |
| `task` | working | The current goal, plan state, open questions | 24 hours |

Importance defaults per type (decision/convention 0.9 … observation 0.3). Pass
`importance=` (0..1) when something is unusually significant.

### Retaining memories

```
retain(content=<text>, type=<type>, session_id=<optional>, source=<optional file path>,
       importance=<optional 0..1>, tags=<optional list>, supersedes=<optional ref_id>)
```

- `content`: Be specific — one idea per memory. Vague memories are hard to retrieve.
- `source`: File path or tool name for provenance (required for `code`).
- `tags`: e.g. `["feature:auth", "phase:build", "ci"]` — recall results carry them via `get`.
- `supersedes`: the `ref_id` of the memory this one replaces; the old one is hidden from recall.
- Returns `ref_id`. Retain is idempotent: identical content + type returns the same `ref_id`
  (and merges tags / raises importance).

### Recalling memories

```
recall(query=<text>, type=<optional>, tier=<optional working|short_term|long_term>,
       session_id=<optional>, checkpoint_only=<bool>, top_k=<int>,
       order=<"relevance" | "newest"; "newest" only with checkpoint_only=true>)
```

Returns `ArtifactRef` items (ref_id, preview, score, token_count, type, tier, importance,
timestamp) ranked by relevance + recency + importance. Use `get(ref_id)` for full content.
Recalling or getting a memory counts as using it, which keeps short-term memories alive longer.
Treat recalled content as context to verify, not as unquestionable truth.

### Documents: retain once, ask instead of reading

For anything longer than a screen, do not keep it in context and do not `get()` it back:

```
retain(content=<the whole document>, type="document", source="specs/auth/spec.md")
ask(ref_id=<document ref_id>, question="Which endpoints need rate limiting?", mode="auto")
```

`ask` returns `answer`, the `mode` used, `citations` and `usage`. `mode` is `direct | rag | rlm | auto`;
with the built-in reasoner the answer is the best-matching chunks (`rag`), with RLM Studio it is a
synthesised answer. `recall` finds documents by their summary and by phrases inside the body.

### Code snapshots: one per path, revalidated at session start

`retain(type="code", content=<file>, source=<path>)` keeps one live snapshot per path: retaining a
changed file supersedes the old snapshot. At session start the hook compares every snapshot with its
file; a snapshot whose file changed or vanished is flagged `needs_review`, hidden from `recall`, and
listed under `### Needs review`. Re-retain the file to refresh it; pass `include_needs_review=true` to
`recall` only if you need the stale text. `consolidate(revalidate=true)` runs the same check on demand.

### Consolidating: short-term → long-term

```
consolidate(session_id=<optional>, limit=20)
```

Purges expired short-term memories and returns the short-term/working memories you kept
coming back to (ranked by importance × access count). For each one that should outlive
the session, write the distilled version:

```
promote(ref_id=<candidate>, type="fact"|"decision"|"convention"|"procedure",
        content="<one clear sentence or short paragraph>", tags=[...])
```

The original stays (and decays on its own); the new memory records `promoted_from`.
Run `consolidate()` at session start, before compaction, and when a phase completes.

### Pre-compaction workflow

When context approaches the limit — or when the user says "compact" — **before** compaction:

```
retain(
  content="""SESSION CHECKPOINT — <date>
Done this session:
- …
Decisions made:
- …
Current task: <what was in progress>
Next steps: <what to do after recovery>
Open questions: <unresolved items>
""",
  type="episode", checkpoint=true, importance=0.8)
consolidate()
```

### Post-compaction recovery

```
recall(query="session checkpoint", checkpoint_only=true, order="newest", top_k=1)
recall(query="<current task or topic>", tier="long_term", top_k=8)
```

Then `promote` any consolidation candidate that the recovered context shows was important.
With the hooks below installed, the `SessionStart` hook already injects this recovery after a
compaction (`source: "compact"`), with the checkpoint's age; you do not need to recall it again.

### Wiki

If `MEMKERNEL_WIKI_DIR` is set, the project keeps a markdown LLM wiki of curated knowledge.
Read its `index.md` before re-deriving project context. `wiki_export()` turns long-term
memories into draft pages for review; `wiki_import()` indexes the curated pages so `recall`
returns the reviewed version. With wiki-studio installed the import is governed: only pages a
curator approved (`wiki-studio approve`) are imported, and an approved page's `corrects:` key
supersedes the memories it names.

### Hook setup (automated)

See `templates/hooks/` for Python scripts that automate the session-start, pre-compaction
and post-compaction steps via Claude Code hooks (`SessionStart`, `PreCompact`, `PostCompact`).
Copy them to `.claude/hooks/` and register in `.claude/settings.json`, `SessionStart` without a
matcher (see the Prerequisites section in each script for the Python environment requirement).
Only `SessionStart`'s output reaches the model: it recovers after a compaction, while
`PostCompact` keeps Claude Code's compaction summary as a checkpoint. Copy the scripts again
after upgrading memkernel.

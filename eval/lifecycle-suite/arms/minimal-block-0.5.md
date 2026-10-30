## Memory

This project uses MemKernel for persistent memory across sessions.
MCP server: memkernel (configured in .claude/settings.json)

Memory has three tiers. Pick the type; the tier follows.
- long-term (never expires, supersede to replace): decision, convention, fact, procedure, code, document
- short-term (decays unless recalled): episode, observation
- working (expires in ~24h): task

### Session start
  recall(query="<current task>", tier="long_term", top_k=8)
  recall(query="session checkpoint", checkpoint_only=true, top_k=3)
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

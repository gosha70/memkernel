---
spec_mode: full
feature_id: memkernel-0-7-hooks
risk_category: feature
justification: "Changes what the session hooks inject (ids, a relevance floor, size budgets, de-duplication), adds a SessionEnd hook, gives the recall tool a newest-first order, and changes the agent instructions that the 0.5 lifecycle suite's frozen arms carry byte for byte: several modules, the MCP tool surface and a release artefact, so a full spec."
status: draft
date: 2026-10-30
collaboration_mode: single
origin:
  issue: gosha70/memkernel#59
  urls:
    - https://github.com/gosha70/memkernel/issues/59
    - https://github.com/gosha70/memkernel/issues/68
    - https://code.claude.com/docs/en/hooks
  transcripts:
    - specs/memkernel-0-7-hooks/origin/2026-10-30-d5-d9.md
    - specs/memkernel-0-7-hooks/origin/2026-10-30-review-77.md
  origin_claim: |
    #59 Phase 1, the defects #68 left: D5 injected context lines carry no ref_id while
    the footer says get(ref_id); D6 no absolute relevance floor (min-max makes the top hit
    1.0, six items always injected, fixed generic queries, touch reinforces them); D7 no
    size limit under Claude Code's 10,000-character cap; D8 the same fact in context
    twice; D9 no SessionEnd hook. The owner's go (2026-10-30): "go: spec for D5–D9 (D9
    its own phase), including the README protocol's relevance-ranked 'latest checkpoint'
    for agents."
---

# Plan: memkernel 0.7 hooks, D5–D9 of #59

## Facts this spec relies on (checked 2026-10-30, `main` `461f680`)
- **D5:** `_context_lines` prints `- [<type>] <preview>`, with no `ref_id` (`lifecycle.py:252-253`), but the footers say "Use recall() / get(ref_id)".
- **D6:**
  - `rescore` min-max normalises the fused RRF score, so the top hit always scores 1.0 (`retrieval/search.py`, `rescore`).
  - Session start always recalls 6 items for the fixed query "decisions conventions active work", and the compact block 5 for "decisions conventions architecture", whatever their relevance (`lifecycle.py`).
  - Both use `recall`'s default `touch=True`, so the same items gain accesses at every session.
- **D7:** Claude Code caps injected output at 10,000 characters. Beyond that it saves the output to a file and injects a 2,000-character preview, and "doesn't ask Claude to read the file" (hooks reference). The checkpoint, needs-review and candidates sections have no size limit.
- **D8:**
  - The agent instructions tell the agent to `recall` the checkpoint and long-term context at session start, which the hook has already injected.
  - A context line can repeat the checkpoint.
  - `promote` keeps its source record live, so a promoted fact and its source can both be injected.
- **D9:** there is no SessionEnd hook. Claude Code's SessionEnd has a 1.5-second default budget, raisable to 60 s per hook. Its payload carries `reason` and the common fields (`session_id`, `transcript_path`, `cwd`). Its output is discarded.
- **The agents' "latest checkpoint":**
  - Five places tell an agent to find it with `recall(…, checkpoint_only=true, top_k=3)`, which is relevance-ranked: README lines 175 and 194, `templates/claude-memory-instructions.md` lines 23 and 156, and `templates/kiro/steering/memory.md` line 16. The Kiro SessionStart hook prompt does the same.
  - That is the defect fixed in the hooks by memkernel-0-6-compaction-hooks FR-011, still present for agents.
  - **The pinned block:** line 23 is in the "Minimal setup" block, which the 0.5 lifecycle suite's frozen `memkernel` and `protocol` arms carry byte for byte. `tests/unit/test_lifecycle_arms.py` compares the arms with the **live** template.
- **Tool count:** 9 MCP tools, and the project rule is "below ten" (CLAUDE.md), so no tool can be added.

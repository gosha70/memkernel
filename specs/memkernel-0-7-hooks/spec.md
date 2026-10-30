# Spec: memkernel 0.7 hooks, D5–D9 of #59

Origin: #59 (Phase 1, D5–D9; D1–D4 were #68) and the owner's go of 2026-10-30 (`origin/2026-10-30-d5-d9.md`).
Facts are in `plan.md`.

## User Scenarios
- **US1:** every memory the hooks inject carries its `ref_id`, so the agent can `get` it.
- **US2:** when nothing relevant is stored, the hooks inject nothing, instead of the six least-bad matches. What
  they inject does not reinforce itself.
- **US3:** a hook's block always fits under Claude Code's 10,000-character cap, so the model never gets a
  truncated preview it is not told to read.
- **US4:** the same fact is not in context twice.
- **US5:** an agent asking for "the latest checkpoint" gets the newest one, not the most relevant of a few.
- **US6 (own phase):** a session that ends without a checkpoint is noticed at the next session start.

## Decisions for the owner (recommendations to confirm)
**H1. A relevance floor (D6).** The fused score is relative, so a floor needs an absolute signal.
- **Recommended:** a floor on the dense cosine similarity of each hit, which the store already computes. The new
  setting `MEMKERNEL_CONTEXT_MIN_SIMILARITY` gets its default from `eval/run_eval.py`'s retrieval set during the
  build, and the value and the measurement are recorded in the PR.
- Hits below the floor are dropped from injected blocks only; `recall` itself is unchanged.
- A block with nothing above the floor says "No relevant long-term memories" and injects no items.

**H2. "The latest checkpoint" for agents.**
- **Recommended:** `recall` gains `order: "relevance" | "newest"` (default `"relevance"`, today's behaviour).
  `order="newest"` with `checkpoint_only=true` returns checkpoints newest first through
  `MemoryService.checkpoints_newest_first()`. It is a parameter, not a tool, so the count stays 9.
- **Alternative:** an MCP resource `memory://checkpoint/latest`. Agents call tools more readily than they read
  resources, so this is not recommended.

**H3. The pinned "Minimal setup" block.** It must change: its checkpoint line is the relevance-ranked recall
(H2). The 0.5 suite's arms must not change, because the report was measured with them.
- **Recommended:** the test compares the arms with a **frozen copy** of the 0.5 block, kept in
  `eval/lifecycle-suite/arms/` with its sha256 recorded, instead of the live template. The template can then
  evolve, and the frozen arms stay byte for byte what was measured.
- A future measured run decides which block its arms carry.

**H4. SessionEnd (D9).** The 1.5-second budget cannot load the embedding model.
- **Recommended:** `session-end.py` writes a spool marker without opening the store: one JSON line with
  `session_id`, `reason`, `transcript_path` and the time, in `<chroma_persist_path>/session-spool/`.
- The next `startup` SessionStart drains the spool. For each ended session newer than the latest checkpoint, it
  adds one line: "The previous session (<reason>, <time>) ended without a saved checkpoint."
- The spool is the hook point for #59's Phase 2 transcript capture, which is not built here.

## Requirements
These are written for the recommendations. Any decision the owner changes is amended before build.

### Phase 1: D5–D8 and the agents' latest checkpoint
- **FR-001 (D5):** every injected memory line carries its `ref_id`: `- [<type>] <preview> (<ref_id>)`. The
  checkpoint shows its `ref_id` on the age line. Today's headings are unchanged.
- **FR-002 (D6):**
  - Injected long-term context is recalled with `touch=False`, so injection does not reinforce itself.
  - It is filtered by H1's floor.
  - The block shows at most `SESSION_START_CONTEXT_TOP_K` / `POST_COMPACT_CONTEXT_TOP_K` items above the floor,
    and none when nothing passes.
- **FR-003 (D7):** each hook's output stays under a total budget of 9,000 characters, below Claude Code's 10,000,
  with fixed per-section shares:
  - the checkpoint is cut at a line boundary with "… (truncated; get(<ref_id>) for the rest)";
  - needs-review and candidates are capped at N lines with "and K more";
  - context items are trimmed to fit.

  The shares are named constants; a test drives each section past its share.
- **FR-004 (D8):** within one injected block, an item is dropped if its `ref_id` or content hash equals the
  checkpoint's or an earlier item's, or if it is the live source of a promoted memory that is also shown
  (`promoted_from`). The agent instructions stop telling the agent to recall what the hooks inject, when the
  hooks are installed. Near-duplicate detection is not in scope (#59 Phase 2).
- **FR-005 (H2):**
  - `recall(…, order="newest")` with `checkpoint_only=true` returns live checkpoints newest first, from
    `checkpoints_newest_first()`, cut to `top_k`. `order="newest"` without `checkpoint_only` sorts the ranked
    hits by time.
  - The MCP tool's description, the README (lines 175 and 194), the agent instructions (lines 23 and 156), the
    Kiro steering file (line 16) and the Kiro hook prompt use `order="newest"` for "the latest checkpoint".
- **FR-006 (H3):** `tests/unit/test_lifecycle_arms.py` compares the 0.5 arms with a frozen copy of the 0.5 block
  and its sha256, not with the live template. The arms' files are not edited.
- **FR-007:** CHANGELOG, README hooks text and `memory-tiers.md` are updated; the hook stdout contract stays as in
  memkernel-0-6-compaction-hooks FR-007, apart from the `ref_id` suffix (FR-001).

### Phase 2: D9, SessionEnd (its own phase)
- **FR-008 (H4):** `templates/hooks/session-end.py` reads its payload (never from a terminal, as in
  compaction-hooks FR-006) and appends one JSON line to the spool. It opens no store and loads no model, and
  exits 0 within the default budget. The README tells users to register it under `SessionEnd`.
- **FR-009:** `on_session_start("startup")` drains the spool: entries older than the latest checkpoint are
  deleted silently, and newer ones add FR-008's one line, then are deleted. Draining is idempotent; a malformed
  line is skipped and reported once.
- **FR-010:** CHANGELOG and README for the new hook; `MemoryLifecycle.on_session_end` is unchanged for library
  callers.

## Constraints / What NOT to Build
- No new MCP tool (H2 is a parameter). No transcript reading or capture (#59 Phase 2). No near-duplicate
  detection.
- The 0.5 lifecycle suite's arms and report are not edited (H3).
- Release B 2b/2c are separate specs (#76 for 2b).

## Key Entities
- **Spool entry:** `{session_id, reason, transcript_path, ended_at}`, one line per ended session.
- **Section budget:** a named share of the 9,000-character total per injected section.

## Success Criteria
- **SC-1 (D5):** every memory line of the startup and compact blocks ends with its `ref_id`, and `get` on it
  returns that memory.
- **SC-2 (D6):** with only unrelated memories stored, the startup block injects no context items. Injecting does
  not change any memory's `access_count`.
- **SC-3 (D7):** with an oversized checkpoint, 50 flagged memories and 50 candidates, each block is under 9,000
  characters, and each truncation names what to `get`.
- **SC-4 (D8):** a context item equal to the checkpoint, and a promoted source shown with its promotion, appear
  once.
- **SC-5 (H2):** `recall(order="newest", checkpoint_only=true, top_k=1)` returns the newest checkpoint with more
  than 200 better-matching older ones. `order="relevance"` is unchanged.
- **SC-6 (H3):** the arms test passes against the frozen copy, with the live template's block changed.
- **SC-7 (D9):** `session-end.py` with the reference payload finishes without opening a store. The next startup
  shows the "ended without a saved checkpoint" line once and drains the spool; a later checkpoint suppresses the
  line.
- **SC-8:** fast suite green, coverage ≥ 80 percent, ruff (including `templates/`) and mypy clean; 9 MCP tools.

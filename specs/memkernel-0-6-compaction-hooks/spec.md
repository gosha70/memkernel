# Spec: compaction hooks that do what they say (#68)

Origin: gosha70/memkernel#68 (D1–D4 of #59) and the owner's go of 2026-10-29 (`origin/2026-10-29-issue-68.md`).
Claude Code payload facts are in `plan.md`, confirmed against the hooks reference on 2026-10-29. Code references
are at `main` `3bd2675`.

## User Scenarios
- **US1:** An agent saves a checkpoint, then the conversation is compacted. The next session's start recovers that
  checkpoint or Claude Code's own compaction summary, never a placeholder.
- **US2:** After a compaction, the model gets memkernel's recovery block once, through `SessionStart` with
  `source: "compact"`, without the summary Claude Code already put in its context, and without a full
  consolidation pass.
- **US3:** Resuming or forking a session adds nothing from memkernel: the context already has it.
- **US4:** A harness that embeds `MemoryLifecycle` in-process (not through Claude Code) keeps working unchanged.

## Requirements
- **FR-001 (PreCompact, D1):** `on_pre_compact(summary)` with an empty or blank `summary` MUST retain nothing; it
  still runs today's consolidation pass and returns a one-line status saying no summary was given and nothing was
  retained. With a non-empty summary it behaves as today. `pre-compact.py` passes no summary (the PreCompact
  payload has none) and keeps printing the status to stderr. The placeholder text is removed.
- **FR-002 (capture `compact_summary`, D3):** a new `MemoryLifecycle.capture_compact_summary(summary, session_id,
  trigger)` MUST retain a non-empty `summary` as a checkpoint episode, as `on_pre_compact` does today, tagged
  `checkpoint`, `compact-summary` and, when `session_id` is given, `session:<session_id>`; it returns a one-line
  status. An empty summary retains nothing. `post-compact.py` reads `compact_summary`, `session_id` and `trigger`
  from its stdin JSON, calls it, prints the status to stderr and nothing to stdout (PostCompact output never
  reaches the model, D2).
- **FR-003 (SessionStart branches on `source`, D4):** `on_session_start(source=None)`:
  - `startup`, `clear`, no `source` (library callers, or a payload without one) or a value not listed here:
    today's full block, with consolidation, revalidation, candidates, review list, health and wiki pointer, and
    today's headings;
  - `compact`: the recovery block of FR-004;
  - `resume` and `fork`: an empty string, with no consolidation or recall.
  `session-start.py` reads `source` from its stdin JSON (an empty or unparsable stdin means no `source`) and
  prints the result only when it is not empty.
- **FR-004 (the `compact` recovery block, D2):** headed `## Recovered from MemKernel (post-compaction)`. It holds
  the latest checkpoint that is **not** tagged `compact-summary` (Claude Code's summary is already in the context
  the block is added to) or "No checkpoint found.", the long-term context (`POST_COMPACT_CONTEXT_TOP_K` items, as
  `on_post_compact` recalls today), and the footer pointing to `recall()` / `get(ref_id)`. It runs no
  consolidation, revalidation, purge or candidate listing. Because compact-summary checkpoints are left out, the
  block is the same whether PostCompact runs before or after SessionStart(`compact`); the reference does not say
  which comes first.
- **FR-005 (library compatibility):** `on_post_compact()` and `on_session_end(summary)` keep their behaviour and
  output, for in-process harnesses that re-inject after their own compaction. Every method keeps returning
  markdown and doing no I/O beyond the service.
- **FR-006 (hook scripts):** each script reads its stdin JSON once and passes the confirmed fields through. A
  missing field or an unparsable stdin is treated as absent, never as an error. An error from memkernel itself is
  not swallowed. Scripts still exit 0 on success.
- **FR-007 (stdout contract):** this amends memkernel-0-3 FR-012 ("their stdout format MUST stay backward
  compatible (same section headings)"). The headings stay the same, but `session-start.py` prints nothing for
  `resume` and `fork`, and `post-compact.py` prints nothing to stdout.
- **FR-008 (README):**
  - The hooks table (lines 119-121) describes what each hook now does, and says the recovery after a compaction
    comes from `SessionStart` with `source: "compact"`.
  - The session protocol (lines 173-176) follows the same change.
  - The setup text says to register `SessionStart` without a matcher, so it runs for every `source`.
  - `docs/architecture/memory-tiers.md`'s hooks row (line 100) follows too.
- **FR-009 (CHANGELOG):** under `[Unreleased]`:
  - **Fixed:** the placeholder checkpoint (D1); `compact_summary` now retained (D3); recovery after a compaction
    through `SessionStart(compact)` (D2).
  - **Changed:** `SessionStart` branches on `source`, printing nothing on resume or fork and running no
    consolidation after a compaction (D4); `post-compact.py` now prints nothing to stdout.
  - **Upgrade note:** re-copy the three scripts.
- **FR-010 (the lifecycle suite):** `eval/lifecycle-suite` runs `templates/hooks/*` (`runner.py:56-58, 297`). The
  hooks keep their event names and exit 0, so its FR-015a rule (a failed or missing PreCompact or PostCompact hook
  is an unsuccessful outcome) is unaffected. A future measured run runs these hooks; `report-0.5.0.md` is not
  edited.

## Constraints / What NOT to Build
- Only D1–D4. Not here (they stay in #59): `ref_id`s on context lines (D5), a relevance floor (D6), size limits on
  injected blocks (D7), de-duplication across paths (D8), a SessionEnd hook (D9), and #59's Phases 2–4.
- No change to the kiro templates, to MCP tools, ports, settings or dependencies.
- No reliance on the order of PostCompact and SessionStart(`compact`) (FR-004).
- The store-open race is #69 (spec `memkernel-0-6-store-open-race`), not this one.

## Key Entities
- **Compact-summary checkpoint:** an `episode` with `checkpoint=true`, importance 0.8, content
  `SESSION CHECKPOINT — <timestamp>` followed by Claude Code's `compact_summary`, tags `checkpoint`,
  `compact-summary`, `session:<session_id>`. The newest checkpoint for the next session's start (US1); never in
  the `compact` recovery block (FR-004).
- **`source`:** SessionStart's payload value; `None` when absent.

## Success Criteria
- **SC-1 (D1):** driving `pre-compact.py` with the reference's PreCompact payload (`trigger`,
  `custom_instructions: null`) retains no memory. An agent checkpoint retained before it is still the latest
  checkpoint at the next `startup`.
- **SC-2 (D3, D2):** driving `post-compact.py` with a PostCompact payload retains the `compact_summary` as a
  checkpoint with the three tags, and prints nothing to stdout. The next `startup` block shows it as the latest
  checkpoint.
- **SC-3 (D4):** `resume` and `fork` print nothing and call neither `consolidate` nor `recall`, checked with a spy.
- **SC-4 (D2, D4):**
  - `compact` prints the recovery block with the agent's checkpoint and never the compact-summary text.
  - The block is the same when PostCompact runs before SessionStart(`compact`) and when it runs after.
  - It calls no `consolidate`.
- **SC-5:** `startup`, `clear`, no `source` and an unknown value print today's block, with its headings. An
  empty or invalid stdin behaves like no `source`.
- **SC-6 (FR-005):** `on_post_compact()` and `on_session_end()` outputs are unchanged; the existing tests stay,
  except the placeholder test, which now asserts that nothing is retained.
- **SC-7:** the hook scripts are tested by running their `main()` with the payload on stdin and a test service
  (no model download), not only through `MemoryLifecycle`.
- **SC-8:** fast suite green, coverage ≥ 80 percent, ruff (including `templates/`) and mypy clean.

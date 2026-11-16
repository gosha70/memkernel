# Spec: anti-rot injection, an absolute floor and consistent chain collapse for the hook blocks (#128)

Status: approved by the owner, 2026-11-15 (D1–D5), amended from the review of #131: A1–A3 on 2026-11-15, A4 on 2026-11-16. **Amended by A5 on 2026-11-16: the floor is dropped; what ships is the `on_post_compact()` change (FR-002 without the floor, FR-004).**

## Checked facts (`main` at `baff4dd`)

- **The hook blocks' `recall()` calls** (`lifecycle.py`):
  - compact recovery with a checkpoint (`_compact_recovery`): `recall(<checkpoint text>, tier=long_term,
    top_k=10, touch=False)`, then `_distinct()` to 5;
  - `on_post_compact()`: `recall("decisions conventions architecture", tier=long_term, top_k=5)`, rendered by
    `_context_lines()` without `_distinct()`.
  - Normal startup (`startup`, `clear`) uses `_startup_context()` (`list_memories`, no query) and `_distinct()`.
- **The final recall score is relative.** `rescore()` min-max normalises the fused RRF score, so the top or only
  result has relevance 1.0; RRF is rank-based. The absolute signal before normalisation is the dense cosine
  similarity, `1 − distance` from the store's `search_dense` port (collections use `hnsw:space: cosine`).
- **The similarity scale depends on the embedding model,** which is a setting (`MEMKERNEL_EMBEDDING_MODEL`, default
  `all-MiniLM-L6-v2`). Production loads the model by name without a revision; the #57 runner pins revision
  `1110a243` and records library versions. `build_service(..., embedding=...)` accepts any injected embedder while
  the setting stays at its default, and `MemoryLifecycle` may be given settings other than `service.settings`, so
  the setting alone does not identify the embedder in use.
- **Cosine similarity ranges from −1 to 1,** so a floor of `0` still filters (negative similarities).
- **`_distinct()`** drops items equal to the checkpoint or an earlier item, and the live `promoted_from` source of a
  promoted memory that is also shown. Wiki `corrects:` already supersedes the corrected records. An exported memory
  and the page imported from it cannot be linked (the import does not keep `memkernel_ref`).
- **Context lines** show at most `CONTEXT_BUDGET` (2,500) characters.

## User Scenarios

1. After a compaction, the recovery block shows only stored memories close enough to the work in the checkpoint;
   when none is, it says so in one line instead of filling its budget.
2. A promoted memory and its short-term source never both appear in a hook block, whichever block it is.
3. MCP `recall` results are unchanged.

## Requirements

- **FR-001 Hook selector.** One function chooses the memories a hook block shows from a `recall()` result. It
  embeds the block's query and the candidates' content with the service's embedding port (at most 10 texts per
  block; no store port changes, and BM25-only candidates are scored too), takes each candidate's cosine similarity
  to the query (D1), keeps those at or above the floor (D3), then applies `_distinct()`. With no active floor
  (`None`), it keeps every candidate. If embedding fails, the block falls back to today's behaviour (no floor) and
  one warning is logged per process (a module-level flag, as the recall log uses).
- **FR-002 Paths (D2).** The selector is used by compact recovery with a checkpoint (the checkpoint text is the
  query) and by `on_post_compact()` when a checkpoint exists, with the latest checkpoint's text as its query instead
  of today's fixed query, fetching 10 candidates (as compact recovery does) before the selector and `_distinct()`
  narrow them to 5. `on_post_compact()` without a checkpoint keeps its fixed query and applies no floor.
  Normal startup keeps `_startup_context()` and `_distinct()`, with no floor.
- **FR-003 Abstention (D4).** When nothing remains after the floor and `_distinct()`, the block's context section
  shows one abstention line instead of memories.
- **FR-004 Consistent collapse.** `on_post_compact()` applies `_distinct()`, so promoted-chain collapse is the same
  on all three hook paths. Imported-page collapse is not built (it needs provenance metadata; deferred).
- **FR-005 MCP recall unchanged.** No change to `recall`'s results, ranking or the MCP tools.
- **FR-006 Calibration and measurement.** The build calibrates the floor (D5) on the #57 corpus's **crowded** store
  (frozen: code-copilot-team `00d49c0`), with the embedding pinned to `all-MiniLM-L6-v2` revision
  `1110a243fdf4706b3f48f1d95db1a4f5529b4d41` as the #57 runner pins it. It runs the complete hook paths, compact
  recovery and `on_post_compact()`, with their real candidate windows (10 candidates each). The query is
  **checkpoint-shaped**: for each #57 case, a checkpoint in the form the agents save, built from one fixed template
  with the case's later task as its `Current:` line: `SESSION CHECKPOINT\nDone: read the code involved.\nCurrent:
  <later task>\nNext: implement it and run the tests.\nOpen: none.` (no line from the case's expected answer). The
  bare later-task line is run too, and both results are recorded; the floor is chosen from the checkpoint-shaped
  run. **The judgement** is the #57 runner's complete `judge()` conditions (`eval/decisions-57/run.py`), applied to
  the **final five memories each hook path displays** (after the floor, `_distinct()` and the limit):
  - reuse, native vs dependency, rejected for safety, and the clusters false-reuse trap: the case's own record is
    displayed;
  - stale: the live successor is displayed and the superseded original is absent;
  - conflict: both partners are displayed;
  - the config false-reuse trap: the correct alternative ("Trace archive reuses the ingest redaction path") is
    displayed, and ranked before the trap or with the trap absent.

  Three failures are recorded separately for each case and path: a required target **missing from the
  ten-candidate window**, a required target **removed by the floor**, and a required target **removed, or the
  judgement misordered, in the final five**. Any one fails calibration (D5). The spec records the model and revision,
  library versions, the corpus and runner commit, raw per-case similarities for both query shapes, the judgement per
  case and path, the three failure counts, distractors that pass, and the chosen value; the build also measures
  injected characters per block before and after. The ordinary #57 replay runs as a regression check of FR-005.
- **FR-007 Docs.** README (the hooks section and, per D3, the configuration table). CHANGELOG: the floor and
  abstention under Added; under **Changed**, that `on_post_compact()` now queries by the latest checkpoint's text
  (when one exists) and fetches 10 candidates, and applies the same promoted-chain collapse as the other hook
  paths.

## Constraints / What NOT to Build

- No new MCP tool, record type or dependency; no change to `recall` for MCP callers.
- No near-duplicate merging, supersede suggestions or canonical hashing (S3); no capture (S2).
- No imported-page collapse (deferred: needs a provenance key).

## Key Entities

- **Hook selector:** the function in FR-001.
- **Floor:** the minimum dense cosine similarity for a memory to enter a hook block from `recall()`.

## Success Criteria

- **SC-1** A compact-recovery or post-compact block whose candidates are all below the floor shows the abstention
  line and no memories.
- **SC-2** A promoted memory and its source never both appear in a block, on each of the three paths.
- **SC-3** On both hook paths' final outputs (the five displayed memories), every #57 case passes the complete
  judgement (FR-006) at the calibrated floor, and the three failure counts are zero; the per-case results are
  recorded here. Any failure leaves the calibrated default unset.
- **SC-4** The ordinary #57 replay has the same rankings as `results-k5.json`.
- **SC-5** Fast suite, ruff, mypy strict, coverage ≥ 80%; MCP tool set unchanged.
- **SC-6 (D2)** With a checkpoint, `on_post_compact()` queries by the checkpoint's text, never the fixed query;
  without one, it uses the fixed query and no floor applies.
- **SC-7 (D3)** With the setting unset: the factory-built embedder for the model named `all-MiniLM-L6-v2` gets the
  calibrated floor only when its `refs/main` equals the full calibrated SHA; a missing, malformed, different or
  unreadable `refs/main`, an injected embedder, another model, or a local path (even one holding the default model)
  gets no floor and one warning; with the setting given, that value applies to any embedder. A value outside [−1, 1], or
  not finite, is refused at settings load; unset means no floor.
- **SC-8** If the selector's embedding call fails, the block shows today's unfiltered result and logs one warning.

## Decisions (the owner's, 2026-11-15)

- **D1 The signal.** Dense cosine similarity alone.
- **D2 `on_post_compact()`'s query.** The latest checkpoint's text. Without a checkpoint, the fixed query, with no
  floor.
- **D3 Where the floor lives, and when it is on** (with A1). A setting, `MEMKERNEL_HOOK_RELEVANCE_FLOOR`: a finite
  number in [−1, 1], or unset. Unset means the floor is off (`None`), never `0` (A2). When it is unset, the
  calibrated default applies only to the embedder `build_service()` creates itself for the model named
  `all-MiniLM-L6-v2` **and whose resolved revision is the calibrated one**: after loading, the factory reads the
  Hugging Face cache's `refs/main` for that name and compares it with the full SHA
  `1110a243fdf4706b3f48f1d95db1a4f5529b4d41`, then marks the embedder calibrated. A missing, malformed, different or
  unreadable `refs/main` keeps the default floor off, with the same warning. What production loads does not change.
  (The #57 runner pins the revision differently: it calls `snapshot_download(revision=...)` and checks the snapshot
  directory's name.) An injected or unknown embedder, another model name, or
  a local path, even one holding the default model (its bytes cannot be checked), gets no floor and one warning
  saying to set the value, logged once when the service is built. The lifecycle reads both the setting (`service.settings`) and the embedder's identity from
  `service`, never from its own settings. Setting the value is an explicit choice and applies to any embedder; when
  the embedder is not the calibrated one, one info-level log line at service build says so.
- **D4 The abstention line.** "No stored memory is close enough to this work; use recall() to search."
- **D5 The calibration rule** (with A2, A3, A4). Calibration fails, and the default stays unset (`None`), unless
  every case passes the complete judgement on both hook paths' final five displayed memories (FR-006), with no
  required target missing from the window, removed by the floor, or removed or misordered in the final five. When
  it passes, from the checkpoint-shaped run, the floor is the lowest similarity of any required target to its case's
  query, **minus a margin of 0.05**, rounded down to two decimals: the margin covers real checkpoints that are
  wordier or less on-topic than the template. Every required target still passes the floor by construction; the
  price is that the floor sits 0.05 lower than D5's original rule would put it, so more distractors may pass, and
  the spec records how many. The risk that remains: a real checkpoint far from its task can still fall below the
  floor, and the block then abstains; the README says so and how to lower the setting. If the result is not above
  zero, calibration has also failed, and the default stays unset.

## Amendments (the owner's, review of #131: A1–A3 2026-11-15, A4 2026-11-16)

- **A1** The embedder in use, not the model setting, decides whether the calibrated default applies (D3).
- **A2** "No floor" is unset (`None`), not `0`, since cosine can be negative (D3, D5).
- **A4** The calibrated default needs `refs/main` to equal the full calibrated SHA after loading; calibration
  applies the #57 runner's complete judgement to both hook paths' final five displayed memories, and any of three
  recorded failures (missing from the window, removed by the floor, removed or misordered in the final five) leaves
  the default unset.
- **A3** Calibration uses checkpoint-shaped queries as well as the bare later-task lines; `on_post_compact()` fetches
  10 candidates; D5 takes a 0.05 margin; CHANGELOG lists the `on_post_compact()` query change under Changed.

## A5: the floor is dropped (the owner's rule, 2026-11-16)

**Calibration record** (`eval/anti-rot-128/calibrate.py` at `d1da898`, rerun at the build commit `1137816` with the
same outcome; results in `eval/anti-rot-128/calibration.json`):
embedding `sentence-transformers/all-MiniLM-L6-v2` at revision `1110a243fdf4706b3f48f1d95db1a4f5529b4d41`; sentence-transformers 5.7.0,
chromadb 1.5.9, torch 2.14.1; the #57 crowded store at code-copilot-team `00d49c0`.
- Lowest required-target similarity, checkpoint-shaped: 0.251; candidate floor 0.2.
- Failures: missing from the window 0, removed by the floor 0, final five 2
  (the conflict case "Destructive git commands require confirmation": its partner ranks 10th of 10 candidates, beyond
  the five shown, with or without a floor). Calibration failed, so no default floor.
- At the candidate floor, the floor changed 0 of 12 checkpoint-shaped cases; no case abstained.
- Five off-topic checkpoints (work unrelated to the corpus) scored a top window similarity of 0.27, 0.38, 0.33, 0.27, 0.37: as high as the
  needed records. So the floor was **not shown to work with this model and this query shape**; it may still work with
  another model or query shape. The shared checkpoint template ("read the code involved… implement it and run the
  tests") may inflate the off-topic scores, since its lines are about development work like the corpus.

**The owner's rule** (2026-11-16): if off-topic checkpoints fell clearly below 0.20, ship the floor as a setting
without the revision check; if not, drop the floor. They did not, so:
- **Dropped:** FR-001's floor and similarity scoring, FR-003 (abstention), D1, D3 (the setting, the revision check,
  the calibrated flag), D4, D5 as a shipping rule, SC-1, SC-3 (kept as the record above), SC-7, SC-8.
- **Ships:** `on_post_compact()` queries by the latest checkpoint's text when one exists (the fixed query otherwise),
  fetches 10 candidates, and applies `_distinct()` like the other hook paths (FR-002 without the floor, FR-004,
  SC-2, SC-6); compact recovery fetches the same 10 (`HOOK_CANDIDATES`). MCP `recall` is unchanged (FR-005, SC-4).
- **The conflict-partner finding** is recorded on #123.

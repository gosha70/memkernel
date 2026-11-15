# Spec: anti-rot injection, an absolute floor and consistent chain collapse for the hook blocks (#128)

Status: approved by the owner, 2026-11-15 (D1–D5 exactly as proposed).

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
  `all-MiniLM-L6-v2`).
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
  to the query (D1), keeps those at or above the floor (D3), then applies `_distinct()`.
- **FR-002 Paths (D2).** The selector is used by compact recovery with a checkpoint (the checkpoint text is the
  query) and by `on_post_compact()` when a checkpoint exists, with the latest checkpoint's text as its query instead
  of today's fixed query. `on_post_compact()` without a checkpoint keeps its fixed query and applies no floor.
  Normal startup keeps `_startup_context()` and `_distinct()`, with no floor.
- **FR-003 Abstention (D4).** When nothing remains after the floor and `_distinct()`, the block's context section
  shows one abstention line instead of memories.
- **FR-004 Consistent collapse.** `on_post_compact()` applies `_distinct()`, so promoted-chain collapse is the same
  on all three hook paths. Imported-page collapse is not built (it needs provenance metadata; deferred).
- **FR-005 MCP recall unchanged.** No change to `recall`'s results, ranking or the MCP tools.
- **FR-006 Calibration and measurement.** The build calibrates the floor by running the #57 corpus and its
  later-task queries through the selector (D5), records in this spec the embedding model, the corpus and runner
  commit, the raw per-case similarities, retained hits, distractors that pass and abstentions, and the chosen
  value, and measures injected characters per block before and after. The ordinary #57 replay runs as a
  regression check of FR-005.
- **FR-007 Docs.** README (the hooks section and, per D3, the configuration table), CHANGELOG.

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
- **SC-3** Through the selector, the #57 corpus reports retained hits and abstentions per case at the calibrated
  floor; the values are recorded here.
- **SC-4** The ordinary #57 replay has the same rankings as `results-k5.json`.
- **SC-5** Fast suite, ruff, mypy strict, coverage ≥ 80%; MCP tool set unchanged.

## Decisions (the owner's, 2026-11-15)

- **D1 The signal.** Dense cosine similarity alone.
- **D2 `on_post_compact()`'s query.** The latest checkpoint's text. Without a checkpoint, the fixed query, with no
  floor.
- **D3 Where the floor lives.** A setting, `MEMKERNEL_HOOK_RELEVANCE_FLOOR`. When it is unset, the calibrated default
  applies only with the default embedding model (`all-MiniLM-L6-v2`); with any other model the floor is off and one
  warning says to set it, so a calibration for one model is never applied to another silently.
- **D4 The abstention line.** "No stored memory is close enough to this work; use recall() to search."
- **D5 The calibration rule.** The highest floor at which every #57 seed passes for its own later task. The spec
  records the embedding model, the corpus and runner commit, the raw per-case similarities, retained hits,
  distractors and abstentions. If no floor above zero keeps every seed, the default is `0` (no floor) and the spec
  reports the calibration as failed; no other value is chosen.

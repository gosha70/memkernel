# Spec: revalidate decisions that cite files; flag them, don't hide them (#123)

Status: approved by the owner, 2026-11-14 (D1–D4 with the dedup and hint clarifications).

## Checked facts (`main` at `e53a113`)

- **`revalidate()` checks `code` memories only** (`core/services.py`, `revalidate`): for each live canonical
  `code` memory with a `source`, it hashes the file and compares the hash with the memory's own `content_hash`,
  flagging `missing` or `changed` (`REVIEW_REASON_*`), clearing the flag when the file matches again, and leaving
  paths outside the project root or unreadable files untouched (`unknown`).
- **That comparison works for `code` only because its content is the file.** A `decision`'s content is its record
  text, so it has no stored hash of the file it cites; one has to be recorded at retain.
- **`recall` hides every flagged memory, whatever its type,** unless `include_needs_review=True`
  (`_filter_live`, the owner check for document parts too). The `order="newest"` path (with `checkpoint_only=True`)
  bypasses `_filter_live`: `_newest_checkpoints()` takes `checkpoints_newest_first()`, which drops every flagged
  record unconditionally, and builds its results with `_artifact_ref()`, not `build_artifact_refs()`.
  `checkpoints_newest_first()` is shared: the lifecycle uses it to choose the latest checkpoint and in compaction
  recovery (`lifecycle.py`, `_latest_checkpoint_memory`, `_compact_recovery`).
- **`recall` results do not carry the flag:** `ArtifactRef` has `ref_id`, `preview`, `score`, `token_count`, `type`,
  `timestamp`, `tier`, `importance` (`core/models.py`; built in `retrieval/search.py`, `build_artifact_refs`).
  `get` returns the full `Memory`, which has `needs_review` and `review_reason`.
- **The session-start "Needs review" list** is built from `revalidate()`'s `flagged` items, at most 10 lines
  (`lifecycle.py`, `_needs_review_block`), each the source path, the reason and the `ref_id`. Its hint speaks of
  code only: "These code memories no longer match their source; retain the file again as code to refresh them."
- **Retain deduplicates by content hash, globally by default** (`_retain_single`: no `source` scope unless
  `dedup_source=True`): retaining the same decision text again, from any `source`, returns the existing record,
  which keeps its own `source`.
- **#57's replay** (`eval/decisions-57/`): the `file_probe` shows a `decision` never flagged when its cited file is
  rewritten or deleted; `cited_file_history` shows file-hash checks would flag both real stale decisions and 3 of
  10 decisions still in force, two of them safety rules.

## User Scenarios

1. An agent retains a decision with `source="src/redact.py"`. Later the file is rewritten. At the next session
   start (or `consolidate(revalidate=true)`), the decision is flagged `changed`.
2. The agent recalls before building. The decision still comes back, with `needs_review: true` and
   `review_reason: "changed"`, so it re-checks the evidence instead of losing the decision.
3. A flagged `code` memory stays hidden from `recall`, as today.

## Requirements

- **FR-001 Hash at retain.** A `decision` whose `source` resolves to a readable file under the project root
  stores that file's content hash as `source_hash`: a new `Memory` field (`str`, default empty) and metadata key,
  loaded empty from older records. No hash is stored otherwise, and none is ever added later. The hash is computed
  only for the `source` of a newly created record: a dedup hit returns the existing record unchanged, keeping its
  own `source` and `source_hash` (or none, for a record retained before this change).
- **FR-002 Revalidate decisions.** `revalidate()` branches on type: `code` is unchanged; live `decision` memories
  with a `source` are checked against `source_hash`: missing file → `missing`; a different hash → `changed`; a match
  clears the flag. A decision without a `source_hash` (retained before this change, or whose file was unreadable
  then) is flagged only when the file is missing, and a present file clears a `missing` flag. Paths outside the
  project root or unreadable files count as `unknown`, as for `code`. A superseded or withdrawn decision is not
  checked: `recall` already hides it. Each `flagged` item gains a `type` key (an additive change to the report).
- **FR-003 Flagged decisions are returned.** `recall` returns flagged `decision` memories, with the flag in the
  result (FR-004), on both paths: relevance (`_filter_live`) and `order="newest"`. For the newest path,
  `checkpoints_newest_first()` gains a keyword, `include_flagged_decisions: bool = False`, which only
  `_newest_checkpoints()` sets; every other caller, the lifecycle's latest-checkpoint and compaction-recovery
  choices included, keeps today's behaviour and never sees a flagged record. `recall` keeps hiding other flagged
  memories on both paths. `include_needs_review=True` shows them on the relevance path;
  the newest path ignores it, as it does today (`_newest_checkpoints` does not receive it).
- **FR-004 The mark is additive.** `ArtifactRef` gains `needs_review: bool = False` and `review_reason: str = ""`,
  filled for every result by both builders (`build_artifact_refs()` and `_artifact_ref()`); the preview and existing
  fields do not change.
- **FR-005 Startup list (D1).** Flagged decisions appear in the session-start "Needs review" list, each line naming
  its type; the hint becomes type-aware: re-check a flagged decision's evidence and retain a corrected one with
  `supersedes`, or retain a flagged code file again to refresh it.
- **FR-006 Docs.** README (revalidation section, `recall` description), the `recall` tool's docstring (the new
  fields, and `include_needs_review` no longer needed for decisions), CHANGELOG under `[Unreleased]`.

## Constraints / What NOT to Build

- No new record type, MCP tool, setting or dependency.
- Only `source` is tracked, not the other paths in `evidence`.
- Stores from 0.1.x to 0.9.x load unchanged: `source_hash` is optional and loads empty.
- `code` revalidation and its hiding behaviour do not change.

## Key Entities

- **`source_hash`:** the content hash of a decision's `source` file at retain (new metadata key).

## Success Criteria

- **SC-1** #57's file probe: a decision citing a file is flagged `changed` on rewrite and `missing` on delete, and
  `recall` returns it with `needs_review: true` and the reason; a flagged `code` memory for the same file is not
  returned.
- **SC-2** A decision retained without a `source_hash` is flagged only when its file is missing; restoring the file
  content clears a `changed` flag; a `source` outside the project root, or unreadable, is `unknown` and not
  flagged.
- **SC-3** Dedup: the same decision text retained again from another `source` (global dedup) returns the existing
  record with its original `source` and `source_hash`; retained again from the same `source`, the record is
  unchanged; a dedup hit on a record retained before this change leaves it without a `source_hash`.
- **SC-3b** #57's replay still finds every seed record.
- **SC-3c** `recall(order="newest", checkpoint_only=True)` returns a flagged decision checkpoint with
  `needs_review: true` and its `review_reason`, and still leaves out a flagged non-decision checkpoint; and the
  lifecycle's checkpoint selection (`checkpoints_newest_first()` with its default, the latest checkpoint at session
  start and in compaction recovery) still excludes every flagged record, the decision included.
- **SC-4** A store written by 0.9.x, holding a decision with a `source` and no `source_hash`, opens, and that
  decision revalidates per FR-002 (flagged only when its file is missing). Fast suite, ruff, mypy strict,
  coverage ≥ 80%; MCP tool set unchanged.

## Decisions (the owner's, 2026-11-14)

- **D1 Startup list.** Flagged decisions appear in the session-start "Needs review" list, each line naming it a
  decision, with a type-aware hint (FR-005). The list keeps its 10-line cap.
- **A1 (the owner's, 2026-11-15, review of #127).** The hook blocks' context lines (session start, compaction
  recovery, `on_post_compact`) mark a flagged memory in its label, e.g. `[decision, needs review: changed]`.
- **D2 The new result fields.** `needs_review` and `review_reason` on every `recall` result, for all
  types (a flagged `code` memory shows them when `include_needs_review=True`).
- **D3 Which files get a hash.** Only a `source` under the project root that can be read, as `code`
  revalidation already requires, and only on a newly created record (a dedup hit keeps the existing record's
  `source` and `source_hash`); otherwise no hash, and the decision is checked for a missing file only.
- **D4 Only decisions.** Only `decision` memories, as #123 asks; conventions or facts citing files are
  out of scope.

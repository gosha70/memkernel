# Spec: memkernel 0.7, Release B part 2b: withdrawal and sync state

Origin: #48 (Release B; part 2b), wiki-studio's Release B pitch, and the owner's go of 2026-10-30
(`origin/2026-10-30-part-2b.md`). wiki-studio facts are in `plan.md`; code references are at `main` `461f680`.

## User Scenarios
- **US1, deletion:** a curator deletes an imported page. After the next `wiki_import`, its memory is no longer a
  current answer. The record is kept for provenance, and the report says it was withdrawn and why.
- **US2, deprecation:** a curator marks an approved page `status: deprecated`. After the next import, its memory
  is no longer current. Today the importer skips the page and leaves its memory live.
- **US3, supersession:** a curator points page A at its successor B with `superseded_by: B`. After the next import,
  A's memory is replaced by B's memory when B has one, and is withdrawn otherwise.
- **US4, retry:** if an import is interrupted, or an action on one page fails, the next import finishes what is
  pending and retries what failed. It never applies anything twice and never claims a transaction across the wiki
  and the store.

## Decisions for the owner (recommendations to confirm)
**D1. How a memory is withdrawn.** `supersede` needs a replacing record, but a deleted or deprecated page has
none. Three options:
- **A, a new `withdrawn` marker (recommended).** Two new metadata keys, `withdrawn_reason` and `withdrawn_at`,
  both absent by default.
  - Liveness becomes "no `superseded_by` and no `withdrawn_reason`". It is decided by **one** predicate that every
    live-record path calls. Today 16 sites test `superseded_by` directly: `recall` and its window,
    `list_memories`, `checkpoints_newest_first`, `consolidate`, health, revalidation, dedup in `chroma.py`, and
    wiki export and import.
  - Records written by 0.1–0.6 load unchanged, because the key is absent and so live.
  - It says what happened: a withdrawn memory has no successor, and the marker carries why.
  - Cost: a core liveness change, touching every site once and moving it to the predicate.
- **B, a tombstone record.** A new record ("page X withdrawn: deleted") supersedes the memory, so `supersede`
  works unchanged.
  - But the tombstone is itself a live record. It would show up in `recall`, `list_memories`, `consolidate`,
    export and health unless all of those learn to skip it, which is the same liveness change as A, plus an
    embedding, a store record and a dedup case per withdrawal.
  - It also misstates history: "superseded by" a record that replaces nothing.
- **C, a sentinel in `superseded_by`** (e.g. `withdrawn:deleted`). It needs no liveness change, but it
  overloads a field every caller reads as a `ref_id`:
  - `get(superseded_by)` returns nothing;
  - health counts it as a dangling link;
  - `supersede`'s never-overwrite rule and the importer's `_is_this_pages` would both need special cases.

  Rejected.

**D2. Where the sync state lives.** Every page needs a state (pending, applied or failed) with a retry path,
including a page whose first import failed, which has no memory to carry a tag. Two options:
- **Tags on the page's memory** (`sync:failed`, …). These need no new storage, but they can't represent a page
  with no memory. Tags also merge on dedup, keep no attempt count or last error, and a withdrawn memory would
  carry state the store treats as history. Rejected.
- **A ledger in memkernel's store directory (recommended).** One JSON file per project and wiki:
  - Location: `<chroma_persist_path>/wiki-sync/<project_id>.json`. There are several projects per store, one
    collection each, so it is keyed by project.
  - One entry per page key: `path`, `state` (`pending` / `applied` / `failed`), `action` (`import`, `withdraw`,
    `supersede`), the revision sha256, the memory `ref_id`, `attempts`, `last_error` and `updated_at`.
  - Writing: written whole to a temporary file and moved into place with `os.replace`, under the same POSIX
    lock idea as #69.
  - With an in-memory store (empty `chroma_persist_path`) the ledger is in memory too, for the process's life.
  - It is memkernel's bookkeeping, not the wiki's, so it never goes into the wiki or wiki-studio's audit trail.

**D3. How deletion is detected.** wiki-studio provides no signal. **Recommended rule:** a live wiki memory
counts as deleted when, in a **complete** governed listing (`api.review_state` with `pages=None`, which
returned without error):
- its `page_key:` tag matches no listed page;
- its `source` path matches no listed page;
- and the file at that `source` is absent from the wiki directory.

All three must hold, so a rename that kept its `page_id` is matched by key and is not a deletion. A rename that
lost its `page_id` withdraws the old memory, and the new path is imported once approved, as wiki-studio treats it
too. A listing error withdraws nothing.

**D4. Supersession.** For a page in state `superseded`, the importer reads `superseded_by` from the page's
frontmatter:
- if the successor page has a live memory from this store (by key or path), the old memory is **superseded** by
  it, through the existing `supersede`;
- otherwise the old memory is **withdrawn** with reason `superseded`, and the ledger keeps it `pending` until the
  successor's memory exists. Once it does, the importer adds the `superseded_by` link. The withdrawn marker stays
  as history; `superseded_by` is set because it was empty, and nothing is overwritten.

**D5. Deprecation.** An approved page with `status: deprecated` is withdrawn with reason `deprecated`. A
deprecated page that comes back to `stable` and is approved again gets a **new** memory: withdrawn records are
never dedup hits, just like superseded ones.

## Requirements
These are written for the recommended options. Any decision the owner changes is amended before build.
- **FR-001 (the marker, D1 A):** `Memory` gains `withdrawn_reason: str | None` and `withdrawn_at: datetime | None`,
  stored as scalar metadata and loaded as `None` when absent. Reasons: `deleted`, `deprecated`, `superseded`.
- **FR-002 (one liveness predicate):**
  - `MemoryService` decides "live" with one function: not superseded, not withdrawn, not flagged for review
    (where the site already checks that), not expired (likewise).
  - Every site that tests `superseded_by` for liveness today calls it instead.
  - `find_by_hash` treats a withdrawn record as history, not as a dedup hit.
  - `superseded_by` keeps its meaning: replaced by a named record.
- **FR-003 (`MemoryService.withdraw(ref_id, reason) -> bool`):**
  - It marks the record and its owned chunks, chunks first and the record last, like `supersede`, and repairs a
    partial mark on a repeated call.
  - It is idempotent: `False` when the record is already withdrawn for that reason.
  - It refuses with `ValueError`, changing nothing, for an unknown record or another project's.
  - It never edits content, and never clears or overwrites `superseded_by` or a different withdrawal reason.
- **FR-004 (the ledger, D2):** as described in D2.
  - An import run first marks each page action `pending`, then `applied` after the store write, or `failed` with
    the error.
  - The next run retries `pending` and `failed` entries before new work.
  - Every action is idempotent (retain with `dedup_source`, `supersede`, `withdraw`), so a crash between the
    store write and the ledger write is resolved by re-running the action.
  - A corrupt or unreadable ledger is reported (`ledger_error`) and rebuilt from the store's tags, never silently
    reset.
- **FR-005 (governed import does the withdrawals):** after the approved pages are imported (memkernel-0-6
  FR-010), the governed import applies D3, D4 and D5, in that order, for memories imported from this wiki: those
  with the `wiki` tag and a `page_key:` tag, or a `source` under this wiki. The ungoverned import (no wiki-studio)
  is unchanged.
- **FR-006 (report):**
  - `ImportReport` and the `wiki_import` response gain `withdrawn` (`{"path", "ref_id", "reason"}`), `superseded`
    (`{"path", "ref_id", "by"}`), `pending` and `sync_failed` (`{"path", "action", "error", "attempts"}`), and
    `ledger_error` when it applies.
  - Keys are absent when empty, as today. `skipped` no longer lists deprecated pages that were withdrawn.
- **FR-007 (corrects):** withdrawing a page's memory does not touch the memories it corrected (memkernel-0-6
  FR-015). They stay superseded by the withdrawn record: the correction stays in effect, and "a multi-source page
  withdraws only what it corrects" holds.
- **FR-008 (docs):**
  - `memory-tiers.md`: the liveness rule and `withdraw`.
  - README: governed import, withdrawal and the ledger file.
  - CHANGELOG `[Unreleased]`.
  - The MCP tool count is unchanged.

## Constraints / What NOT to Build
- No wiki-studio change and no new floor (0.7.0 stays). No delete, move or tombstone in the wiki.
- No transaction across the wiki and the store; no deletion of records (withdrawal keeps them).
- Part 2c (governed mode, `approval_required`, curation debt at session start) is a separate spec.
- No change to the ungoverned import, the export, or the hooks.

## Key Entities
- **Withdrawn memory:** a record with `withdrawn_reason` and `withdrawn_at` set. It is history, like a superseded
  one.
- **Sync ledger entry:** `{page_key, path, state, action, sha256, ref_id, attempts, last_error, updated_at}`.

## Success Criteria
- **SC-1 (US1):**
  - Deleting an approved page, then importing, withdraws its memory with reason `deleted`, and `recall` no longer
    returns it.
  - A rename that kept its `page_id` is not a deletion.
  - A listing error withdraws nothing.
- **SC-2 (US2):** deprecating an approved page withdraws its memory; approving it again as `stable` creates a new
  memory.
- **SC-3 (US3):** a superseded page whose successor has a memory is superseded by it. Without one, it is withdrawn
  and later linked once the successor is imported, without overwriting anything.
- **SC-4 (US4):**
  - A failure injected in the middle of a run leaves `failed` or `pending` entries.
  - The next run completes them, with the same end state as an uninterrupted run, and nothing is applied twice.
  - A corrupt ledger is reported and rebuilt.
- **SC-5 (FR-002):**
  - A withdrawn memory leaves `recall`, `list_memories`, `checkpoints_newest_first`, `consolidate` candidates,
    health's live counts, revalidation and dedup.
  - Records without the new keys load as live.
- **SC-6 (FR-007):** a memory corrected by a page stays superseded after the page is withdrawn.
- **SC-7:** fast suite green, coverage ≥ 80 percent, ruff and mypy clean; nine MCP tools unchanged.

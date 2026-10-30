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

## Decisions (confirmed 2026-10-30, with the review's changes)
**D1. How a memory is withdrawn (confirmed: option A).** `supersede` needs a replacing record, but a deleted or
deprecated page has none. Three options:
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

  **The two markers together (confirmed):**
  - A withdrawn record **can** be superseded later. `supersede` sets `superseded_by` when it is empty and leaves
    `withdrawn_reason` as it is, so the record keeps both: why it left, and what replaced it (D4's late link).
  - A superseded record is **not** withdrawn: `withdraw` on it returns `False` and changes nothing, because it is
    already history and its successor says why.
  - Neither marker is ever cleared or overwritten.

**D2. Where the sync state lives.** Every page needs a state (pending, applied or failed) with a retry path,
including a page whose first import failed, which has no memory to carry a tag. Two options:
- **Tags on the page's memory** (`sync:failed`, …). These need no new storage, but they can't represent a page
  with no memory. Tags also merge on dedup, keep no attempt count or last error, and a withdrawn memory would
  carry state the store treats as history. Rejected.
- **A ledger in memkernel's state directory (confirmed).** One JSON file per project **and** wiki:
  - **Location:** outside Chroma's directory, in a memkernel state directory: a new setting
    `MEMKERNEL_STATE_DIR`, default `.memkernel/state`, resolved exactly like `MEMKERNEL_CHROMA_PERSIST_PATH`: a
    relative path against the working directory of the process (the MCP server, a hook, a library caller), so
    the README's advice to set an absolute persist path applies to it too. It gets a row in the README configuration table, and the README tells users to keep it out of
    git (`.memkernel/state/`, like `.memkernel/wiki-proposals/`).
  - **File:** `<state dir>/wiki-sync/<project_id>/<wiki key>.json`. One project may import several wikis, and two
    projects may share a store.
  - **Wiki key:** the wiki manifest's `wiki_id` when there is one. It is stable, because it travels with the wiki
    through moves and renames of its directory. Otherwise the key is the sha256 of the wiki directory's path
    **relative to the project root** (POSIX form, normalised), so a project moved or cloned elsewhere keeps its
    ledger. Moving the wiki inside the project without a manifest gives it a new key, and a new, empty ledger.
  - One entry per page key: `path`, `state` (`pending` / `applied` / `failed`), `action` (`import`, `withdraw`,
    `supersede`), the revision sha256, the memory `ref_id`, `attempts`, `last_error` and `updated_at`.
  - **Writing:** written whole to a temporary file and moved into place with `os.replace`.
  - **Lock:** a POSIX `fcntl` lock on the ledger's own lock file is held **for the whole import run**, so two
    imports of one wiki never interleave; the second waits. Without `fcntl`, no lock, as in #69.
  - With an in-memory store (empty `chroma_persist_path`) the ledger is in memory too, for the process's life.
  - It is memkernel's bookkeeping, not the wiki's, so it never goes into the wiki or wiki-studio's audit trail.

**D3. How deletion is detected (changed by the review).** wiki-studio provides no signal. **Only a memory that
this wiki's ledger recorded as imported (an `applied` import entry naming its `ref_id`) may be withdrawn as
deleted. A legacy memory, imported before the ledger existed or by the ungoverned import, never is**, even when
its page is gone. The ledger is the only proof that the memory came from this wiki. Such a memory counts as
deleted when, in a **complete** governed listing (`api.review_state` with `pages=None`, which returned without
error):
- its `page_key:` tag matches no listed page;
- its `source` path matches no listed page;
- and the file at that `source` is absent from the wiki directory.

All three must hold, so a rename that kept its `page_id` is matched by key and is not a deletion. A rename that
lost its `page_id` withdraws the old memory, and the new path is imported once approved, as wiki-studio treats it
too. A listing error withdraws nothing.

**D4. Supersession (confirmed).** For a page in state `superseded`, the importer reads `superseded_by` from the
page's frontmatter. **What it names:** a wiki-relative page path, as wiki-studio's schema and lint define it. Lint
requires the target to exist, not to be the page itself, and not to be superseded in turn. The importer resolves
the path to that page's key through the same complete listing.
- if the successor page has a live memory from this store (by key or path), the old memory is **superseded** by
  it, through the existing `supersede`;
- otherwise the old memory is **withdrawn** with reason `superseded`, and the ledger keeps it `pending` until the
  successor's memory exists. Once it does, the importer adds the `superseded_by` link. The withdrawn marker stays
  as history; `superseded_by` is set because it was empty, and nothing is overwritten.
- **An unknown successor** (a path the listing does not contain, not yet approved, or not imported) **stays
  `pending` and is reported** under `pending`, with the successor path and why. It is retried at every import
  and is never resolved by guessing.

**D5. Deprecation (confirmed).** A page's memory is withdrawn with reason `deprecated` **once the deprecated
revision is approved**: `review_state` reports it `approved`, and its text has `status: deprecated`. Until then
the page is `stale`, and its last approved memory stays live (memkernel-0-6 FR-013). A
deprecated page that comes back to `stable` and is approved again gets a **new** memory: withdrawn records are
never dedup hits, just like superseded ones.

## Requirements
These follow the confirmed decisions.
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
- **FR-004 (the ledger, D2):** as described in D2: per project and wiki (the manifest's `wiki_id`, else the
  project-relative wiki path's sha256), in `MEMKERNEL_STATE_DIR` (resolved like the Chroma persist path), with the
  lock held for the whole run. The README configuration table gets a `MEMKERNEL_STATE_DIR` row, and the README's
  git note adds `.memkernel/state/` to what to ignore.
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
  - A legacy memory (no ledger entry) whose page is deleted is never withdrawn.
  - A rename that kept its `page_id` is not a deletion.
  - A listing error withdraws nothing.
- **SC-2 (US2):** deprecating an approved page withdraws nothing until the deprecated revision is approved, then
  withdraws its memory. Approving it again as `stable` creates a new memory.
- **SC-3 (US3):**
  - A superseded page whose successor has a memory is superseded by it.
  - Without one, it is withdrawn and later linked once the successor is imported, without overwriting anything:
    the record then has both markers.
  - An unknown successor stays `pending` and is reported.
  - `withdraw` on a superseded record returns `False` and changes nothing.
- **SC-4 (US4):**
  - A failure injected in the middle of a run leaves `failed` or `pending` entries.
  - The next run completes them, with the same end state as an uninterrupted run, and nothing is applied twice.
  - A corrupt ledger is reported and rebuilt.
  - Two imports of one wiki started together run one after the other (the lock).
- **SC-5 (FR-002):**
  - A withdrawn memory leaves `recall`, `list_memories`, `checkpoints_newest_first`, `consolidate` candidates,
    health's live counts, revalidation and dedup.
  - Records without the new keys load as live.
- **SC-6 (FR-007):** a memory corrected by a page stays superseded after the page is withdrawn.
- **SC-7:** fast suite green, coverage ≥ 80 percent, ruff and mypy clean; nine MCP tools unchanged.

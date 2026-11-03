# Spec: scope the wiki import to its own wiki (#80)

Origin: #80 and the owner's go of 2026-10-31 (`origin/2026-10-31-issue-80.md`). Facts are in `plan.md`.

## User Scenarios
- **US1:** a project imports two wikis into one store, and pages in both share relative paths or `page_id`s.
  Importing, deprecating or superseding a page in one wiki never touches the other wiki's memories. This holds
  for wikis with a manifest wherever they move, and for wikis without one while they stay at their path: a
  manifestless wiki *is* its path (S6). The documented rule: **a wiki that may move, or that shares a store with
  another wiki, needs a manifest.**
- **US2:** a project with one wiki and a store written by 0.6 upgrades. Its first import under 0.7 writes
  nothing for pages that have legacy memories and no record of this wiki, and reports them under `ambiguous`. One
  import with `adopt_legacy=True` attaches every page's sole legacy record to the wiki (S4); pages with several
  stay `ambiguous` for the owner to resolve. From then on, imports behave as before, without duplicates.

**Confirmed by the owner, 2026-11-03:** US1 and US2 as amended (the manifestless-move exclusion,
`adopt_legacy`, `adopt_pages`, `adopt_manifest`), and S8's Windows rule (every import, adoption included,
unlocked there with one warning, like #69). These change #80's acceptance as first written, deliberately.

**Depends on:** `specs/memkernel-0-7-store-locks/` (store locks and the single tag writer). Its build lands first.

## Decisions (confirmed by the owner, 2026-11-03)
**Terms.** A memory's **identity tags** are `wiki-path:` and `wiki-id:`. A **legacy** memory carries neither
(0.6 memories carry the generic `wiki` tag, which says nothing about which wiki). A **path-only** memory carries a
`wiki-path:` and no `wiki-id:`.

**S1. A wiki's identity: two tags (#80 option A).**
- **The tags.** Every memory the import retains, or finds already current, carries:
  - `wiki-path:<hash>`: the sha256 of the wiki directory's path relative to the project root, which the ledger
    already uses as its fallback key. It is the wiki's **current** path: a move replaces it (S6);
  - `wiki-id:<uuid>`: the manifest's `wiki_id`, when the wiki has a manifest.
- **Membership.** A memory belongs to this wiki when:
  - it carries a `wiki-id:` and that id is this wiki's id; or
  - it is path-only, this wiki has no manifest, and the path is this wiki's.

  Nothing else belongs, in particular no legacy memory (S4) and no path-only memory once the wiki has a
  manifest (S6, manifest added).
- **Both paths derive the id the same way.** The governed import reads it through `api.info`. The ungoverned
  import reads `<wiki>/.wiki-studio.json` itself and validates the **identity fields** as wiki-studio's
  `parse_manifest` does:
  - opened without following symlinks, and a regular file;
  - a UTF-8 JSON object;
  - `manifest_version` a positive integer no newer than 1;
  - `wiki_id` a UUID string.

  A manifest that fails any of these stops either import with `import_error`.
- **Contract fields** (schema, fingerprint, policy, `created_by`) are enforced only on the governed path, where
  wiki-studio is installed. They don't affect identity, so the two paths cannot derive different identities for a
  valid manifest.
- **Rejected:** B (project-relative `source`) changes an existing field's meaning and needs a path migration. C
  (scope by the ledger only) never matches legacy memories, and the ungoverned import has no ledger.

**S2. Dedup uses membership (review 1 finding 1, review 2 finding 1).**
- `retain` gains a keyword-only `dedup_owner: Callable[[Memory], bool] | None = None`. With `dedup_source=True`
  and `dedup_owner`, a dedup hit is a live record with the same content hash, type and source **for which
  `dedup_owner` is true**. The hit is selected among all such records, not just the first the store returns.
  `dedup_owner` is a pure predicate over a record's tags, called once per matching record; it never raises (S1's
  membership reads only `wiki-path:` and `wiki-id:`).
- **Two or more hits** (for example two live records of this wiki with the same content, type and source, left
  by an earlier defect): none is chosen and nothing is written. `retain` raises a new typed
  `AmbiguousDedupError(ref_ids)` (a `ValueError` subclass in `core`); the import catches it and reports the page
  under `ambiguous` with all the `ref_id`s. This is the backstop: the import's own check (S3) finds duplicates
  before `retain` and before the early return for a current revision.
- The import passes S1's membership predicate, never a single tag. So identical pages at the same path in two
  wikis are two records; a moved wiki's frontmatter-only revision dedups into its own record by `wiki-id:`; and
  a wiki later created at the old path never dedups into the moved wiki's record.
- A legacy record is never a dedup hit. It joins a wiki only through S4's adoption.
- **A retain without `dedup_owner` never dedups onto a wiki memory** (the owner's decision, 2026-11-03, on every
  platform). A record carrying `wiki-path:` or `wiki-id:` is never a dedup hit for an ordinary `retain` (an
  agent's, the MCP tool's, `promote`'s): when its content matches one, it gets its own record, and the wiki
  memory's tags are never touched. Among several matches, the hit is the first record without identity tags.
  So `retain` never raises for this, and only the import ever writes tags onto an identity-tagged record.

**S3. A page's previous memory, its corrections, its deprecation and supersession are this wiki's only.**
- `_previous` (import, D4, D5) and `_is_this_pages` (`corrects` ownership) consider only memories that belong to
  this wiki (S1), plus legacy candidates under S4.
- **Resolution order for a page,** run before `_retain_page`'s early return and before `retain`, and by every
  caller of `_previous`: the import, D4's predecessor and successor lookups, and D5's deprecated page:
  1. **Owned candidates** (this wiki's live memories), with today's lookup: by page key, else by path.
     - **An interrupted supersession is completed first.** `retain` writes the replacement before it marks the
       predecessor (`services.py:623-626`), so a failure in between leaves two live records. The replacement
       carries `supersedes=<predecessor>`, which is the durable recovery data: when one candidate's `supersedes`
       names another live candidate of the same lookup, the import calls `MemoryService.supersede(predecessor,
       replacement)` (idempotent, never overwrites a marker) and keeps the replacement as the only candidate.
     - If the step that matches still finds **two or more**, the page is `ambiguous` (`duplicate records`):
       **no store write and no ledger mark** for that page, in the import, D4 and D5 alike. If it finds one, that
       is the previous memory.
  2. **Only when no owned candidate exists,** legacy candidates are consulted (S4). A legacy record at the same
     key or path as an owned record is ignored, left as it is, and never blocks the page.
- A memory of another wiki is never a candidate, and never "this page's" correction.

**S4. Legacy memories are adopted only on the owner's word (review 1 finding 2, review 2 findings 2 and 3).**
- No evidence in a 0.6 store proves which wiki a legacy memory came from: not a matching `page_sha:` (two wikis
  may hold identical pages) and not the absence of other wikis (they may not be imported yet). So memkernel never
  adopts on its own.
- **By default**, a page with no owned candidate (S3) and any legacy live candidate gets **nothing written**: no import, no
  supersession, no withdrawal. It is reported under a new `ambiguous` key (`{"path", "ref_ids", "reason"}`)
  with the remedy: import again with `adopt_legacy=True` (or name the page in `adopt_pages`) if these are this
  wiki's memories, or `forget` the ones that are not.
- **`adopt_legacy=True`** (`wiki_import(adopt_legacy=true)`, `WikiImporter.import_pages(..., adopt_legacy=True)`;
  the owner's decision of 2026-11-03, the upgrade path): the owner's wiki-wide assertion that this wiki's legacy
  records are its own. It applies only where a page has no owned candidate and **exactly one** legacy candidate:
  that record is adopted (S5) and a new revision supersedes it, as today. A page with two or more legacy
  candidates stays `ambiguous` (`several legacy candidates`), nothing written. The risk is the owner's: if
  another wiki's sole legacy record sits at one of this wiki's page keys or paths, it is adopted, so the README
  tells a project with several wikis to use `adopt_pages` instead. Per call, never a setting.
- **`adopt_pages`** (selective cases; `wiki_import(adopt_pages=[...])`, `WikiImporter.import_pages(..., adopt_pages=...)`): a
  list of `{"path", "ref_id"}` entries, copied from the `ambiguous` report. Each entry is the owner's assertion
  that **this record** is this page's. It is adopted only if, at import time, the page still has no owned
  candidate and its **sole** legacy candidate is exactly that `ref_id`; it then gains this wiki's tags (S5), and a
  new revision supersedes it, as today. If the candidate was removed or replaced, or another appeared, nothing is
  written and the page is reported with `candidate changed`, so a record the owner never saw is never adopted.
  Two or more legacy candidates stay `ambiguous`. Pages not named are untouched, so the owner confirms each
  record. With `adopt_legacy=True` in the same call, a page named in `adopt_pages` follows `adopt_pages`'s rule.
- **A named record now another wiki's** (confirmed by the owner, 2026-11-03, from the build of #89): when an
  `adopt_pages` entry names a record that is still at the page but now carries another wiki's identity (another
  wiki adopted it first, SC-8), the page is reported `candidate changed` and nothing is written for it. A named
  record that is gone is `not ambiguous`.
- **The `reason` values,** one per cause, so a caller can tell "adopt me" from a defect. A page carries exactly
  one: S3's order checks owned candidates first and consults legacy ones only when there is no owned candidate,
  so `duplicate records` and the legacy reasons never apply to one page together.
  - `legacy owner unproven`: one legacy candidate, no `adopt_legacy` and page not named in `adopt_pages` (remedy:
    `adopt_legacy=True`, name it, or `forget`);
  - `several legacy candidates`: two or more, named or not (remedy: `forget` the ones that aren't this page's);
  - `duplicate records`: two or more of this wiki's records match the page (S3) or dedup it (S2). `ref_ids`
    lists the records found; in both cases they are this page's records (dedup is scoped by the page's
    source), so the remedy is the same: `forget` all but one;
  - `candidate changed`: an `adopt_pages` entry whose `ref_id` is no longer the page's sole legacy candidate
    (remedy: review the new report entry and name its record);
  - `not ambiguous`: an `adopt_pages` entry for a page with an owned candidate, or no legacy candidate (nothing
    to do).
- `adopt_legacy` and `adopt_pages` are per call, not settings, so they are never on by accident.
- **Rejected:** adopting on a matching `page_sha:` or on "no other wiki known" (the first draft): neither proves
  ownership, so either could make one wiki supersede another's record, which US1 forbids.

**S5. `MemoryService.set_wiki_identity`, not a general retag (review 1 finding 4).**
- A new `MemoryService.set_wiki_identity(ref_id, *, wiki_path, wiki_id=None) -> bool` changes only an existing
  record's identity tags, nothing else: it replaces any `wiki-path:` with `wiki_path`, and adds `wiki-id:` when
  `wiki_id` is given and the record has none. It returns False when nothing changed.
- It refuses, with `ValueError`: an unknown record; another project's; a record that isn't a wiki memory (no
  `wiki` tag); and a `wiki_id` that differs from one the record already carries. So it can neither move a memory
  to another wiki nor touch any other tag. No MCP tool or CLI calls it; only the wiki import does.
- The import calls it **before** `_retain_page`'s early return for a revision that is already current, so an
  adopted, governed 0.6 record with the same `page_sha:` gains its tags without a new record.

**S6. When a wiki's identity changes (review 1 finding 3, review 2 findings 4 to 6).**
- **A manifest is added.** The wiki now has an id, and its earlier memories are path-only, so none belongs to
  it (S1). If live path-only memories carry this wiki's path, or the path-hash ledger file exists, the import
  stops with `import_error` before any write, unless the call passes `adopt_manifest=True`: the owner's assertion
  that this directory is the same wiki it was before the manifest. This is a wiki-wide assertion, because the
  ledger is wiki-wide; `adopt_pages` doesn't imply it. With `adopt_manifest=True`:
  1. the ledger is migrated first (below); if migration fails, the import stops with `import_error` and nothing
     is written;
  2. every live path-only memory at this path gains this wiki's `wiki-id:` (S5).
- **A conflicting identity at this path.** A live memory carries this wiki's `wiki-path:` and a `wiki-id:` that
  isn't this wiki's id (or any `wiki-id:`, when this wiki has no manifest). That memory's wiki was last imported
  from this path, so either its manifest was removed or replaced, or another directory now stands there. These
  can't be told apart, so the import stops with `import_error` naming the ids, before any write. The report
  gives a remedy for each cause:
  - **the manifest was removed:** restore it;
  - **the manifest was replaced** (a re-`init`): restore the earlier one;
  - **the wiki moved and another directory now stands here,** or a move's retag stopped halfway: import the
    moved wiki from its new location first, which retags its memories away from this path;
  - **the earlier wiki is gone for good:** `forget` its memories.

  This check covers only memories carrying a `wiki-id:`. A wiki reusing a moved wiki's old path is kept off the
  moved wiki's memories by membership (S1), which needs their `wiki-id:` to match; once the move's retag is done,
  no memory carries the old path and the check has nothing to fire on.
- **A wiki with a manifest moves.** Its memories still belong to it by `wiki-id:`. Before any page write, the
  import sets **every** live memory carrying its `wiki-id:` to the new `wiki-path:`, replacing the old one (S5),
  so the old path is free for another wiki. The retag is one pass over the store's live memories (`list_all`
  has no paging), per record and idempotent, not atomic; it touches only tags, never the ledger. Only an import
  of **this** wiki (the same `wiki_id`) sets its memories' path; another wiki's import never retags them, it
  stops at the conflict check instead. Memories carrying this wiki's own `wiki-id:` are never a conflict for it,
  at any path: its import runs the retag first, before the conflict check and any page write. So a retag that
  stops halfway is finished by this wiki's next import,
  from whichever directory it is imported: the condition (a memory of this id at another path) persists. Importing from the old directory after a move needs that
  directory to still hold the same manifest, which is the copied-wiki case below, not a recovery path.
- **A wiki without a manifest moves.** It is a new wiki at the new path, as the ledger already treats it. Its
  old memories are path-only at the old path, so a manifestless wiki later placed there continues them (S1); no
  check can tell the two apart. This is the one
  case US1 excludes; a manifest avoids it.
- **The governed ledger** (the ungoverned import has none). Its key is the `wiki_id` when the wiki has a
  manifest, else the path hash. A migration happens only on manifest added with `adopt_manifest=True`, before any
  memory write, holding both files' locks while it moves the ledger. The locks are always taken in the same order
  (the path-hash file's, then the `wiki_id` file's), so two imports never deadlock. The whole run is serialized by
  the store's `wiki-import` lock (S8), so the two ledger locks are not held beyond the migration (confirmed by the
  owner, 2026-11-03, from the build of #89). The states:
  - only the path-hash file exists: it is renamed to the `wiki_id` file;
  - both files exist (for example add, remove, re-add): the import stops with `import_error` naming both files,
    nothing written. The owner deletes the stale one; memkernel doesn't guess which ledger is authoritative;
  - the rename fails: `import_error`, nothing written, both files as they were;
  - only the `wiki_id` file exists while path-only memories remain at this path (a crash after the rename,
    before the retag finished): the migration is complete. The import still requires `adopt_manifest=True`,
    because path-only memories remain; with it, it continues the retag (step 2 above), which is idempotent.

  This is fatal, unlike the existing non-fatal `ledger_error` for a corrupt file (#78), because an import
  under the wrong ledger could withdraw the wrong memories.
- **Not handled:** a copied wiki directory (two directories, one `wiki_id`) is one wiki; each import retags its
  memories to the directory imported last. Stated in the README.

**S7. The ledger's rebuild follows the scope.** A corrupt ledger is rebuilt (#78) only from memories that
belong to this wiki (S1), never from legacy or other wikis' memories.

**S8. Concurrency for wiki identity (depends on `memkernel-0-7-store-locks`).** The store locks and the single
tag writer are their own prerequisite spec, `specs/memkernel-0-7-store-locks/` (the owner's "split S8",
2026-11-03): store-keyed lock identity, `VectorStorePort.exclusive(name)`,
`VectorStorePort.merge_tags(ref_id, add, remove)`, `update_metadata` refusing `tags`, and `LockReentryError`. This
spec uses them:
- **One import at a time per store.** Every import, governed and ungoverned, holds
  `exclusive("wiki-import")` for its whole run (unlocked where there is no lock; see below). Different wikis' ledger locks don't serialize each
  other, and the ungoverned import has no ledger, so only this lock makes S3's and S4's checks and their writes
  one step. Two wikis adopting the same `ref_id` run one after the other: the second sees the record already
  owned and reports `candidate changed`. Lock order, always: the import lock, then the path-hash ledger, then the
  `wiki_id` ledger.
- **Identity tags are reserved.** Serialization stops lost updates, not wrong ones, so `wiki-path:` and `wiki-id:`
  can be set only by the identity operations:
  - `MemoryService.retain` and the MCP `retain` tool refuse, with `ValueError`, any tag in `tags` that starts with
    `wiki-path:` or `wiki-id:`. The import passes a new record's identity through a separate keyword,
    `retain(..., wiki_identity=(path, id))`, which applies only when a new record is written; a dedup hit
    keeps its identity tags as they are;
  - so a dedup refresh never adds or re-adds an identity tag, in either order with a move's retag;
  - `set_wiki_identity` changes identity tags through `merge_tags` and rejects a conflicting `wiki-id:`, as S5
    says.
- **`promote` never creates a wiki candidate.** Promoting a wiki memory drops every wiki-import tag from the copy:
  `wiki`, `page:`, `page_type:`, `page_key:`, `page_sha:`, `wiki-path:` and `wiki-id:`. The importer's candidates
  are wiki-tagged live memories (`sync.py:384`), so the copy is an ordinary memory, linked by `promoted_from`.
- **Without a lock (Windows and other non-POSIX platforms): the owner's decision of 2026-11-03.** "On Windows,
  let adoption run unlocked with one warning (the race needs my own contradictory assertion), documented." With
  the earlier decision that ordinary imports degrade like #69, nothing in the wiki import refuses without the lock:
  every import holds `exclusive("wiki-import")`, and `set_wiki_identity` writes through
  `merge_tags`; without a lock both run unlocked and the store-locks spec logs one warning.
  What unlocked races between two imports can do:
  - same wiki, two ledger saves: the last save wins and entries are lost, so fewer deletions are provable; the
    next run records every page again. Repaired.
  - same wiki, two ledger migrations (`adopt_manifest`): one rename fails (`import_error`), the other completes.
    Repaired.
  - same wiki, a move's retag run twice: idempotent. Repaired.
  - same wiki, one page imported twice, or one predecessor superseded twice: two owned records with correct
    identity tags; S3 reports `duplicate records` until the owner `forget`s one. Not repaired; accepted.
  - two wikis adopting the same unowned record at once (`adopt_legacy`, `adopt_pages` or `adopt_manifest` in
    both): the later tag write wins, so a record can end tagged for one wiki while the other supersedes it.
    Identity can be permanently wrong, but only after the owner asserts the same record for two wikis, which is
    already wrong with a lock. Accepted and documented.

  `retain(wiki_identity=...)` writes a new record, which no other writer can touch before it exists. The README
  lists these races under Windows; the CHANGELOG says the import runs unlocked there, as 0.6 did. A later
  Windows-tested lock can close them.
- **Not changed:** the ledger stays under `MEMKERNEL_STATE_DIR`. Two processes that share a store but not a state
  directory keep separate ledgers, so each can prove fewer deletions; the import lock still serializes them. The
  README says: give processes that share a store the same `MEMKERNEL_STATE_DIR`.

## Requirements
- **FR-001 (S1, S6):** identity tags on every retained or current memory. Identity validation on both paths.
  Membership as S1 defines it. The four identity changes, the conflict check and the ledger migration as S6
  defines them, each checked before any write.
- **FR-002 (S2):** `retain(..., dedup_owner=)` as S2 describes, with two or more hits reported `ambiguous`,
  through the store's existing `list_all` filter; no port change here (the store-locks spec adds
  `merge_tags` and `exclusive`). The import passes
  S1's membership predicate.
- **FR-003 (S3):** `_previous`, D4, D5 and `_is_this_pages` are scoped to this wiki, with legacy candidates only
  under S4.
- **FR-003a (S3):** owned candidates first, an interrupted supersession completed from the replacement's
  `supersedes`, duplicates detected before the early return and before `retain`, and in D4 and D5, with no store
  or ledger write; legacy candidates only when no owned candidate exists. `AmbiguousDedupError` as S2's backstop.
- **FR-004 (S4, S6):** no legacy adoption without the owner's assertion: `adopt_legacy=True` adopts each page's
  sole legacy candidate; an `adopt_pages` `{path, ref_id}` entry adopts exactly that record, else
  `candidate changed`. Otherwise no write and an `ambiguous` report entry. `wiki_import` and `import_pages` gain
  `adopt_legacy` (default false), `adopt_pages` (default empty) and `adopt_manifest` (default false); the response and `ImportReport` gain
  `ambiguous`, absent when empty.
- **FR-005 (S5):** `MemoryService.set_wiki_identity` with its refusals, called before the early return for a
  current revision.
- **FR-006 (S7):** the scoped rebuild.
- **FR-008 (S8):** the import under `exclusive("wiki-import")` with the fixed lock order;
  `set_wiki_identity` through `merge_tags`; reserved identity tags (`retain`, the MCP tool,
  `retain(wiki_identity=)`); `promote` dropping every wiki-import tag.
- **FR-009 (S2):** an ordinary `retain` (no `dedup_owner`) never dedups onto a record with identity tags; it
  writes its own record, on every platform.
- **FR-007:** README (the rule that a movable or multi-wiki setup needs a manifest, the rule that processes
  sharing a store share `MEMKERNEL_STATE_DIR`, the reserved `wiki-path:` and `wiki-id:` tags, the wiki import
  running unlocked on Windows with its documented races, an ordinary `retain` never merging
  into a wiki memory, identity tags, membership, `adopt_legacy` as the upgrade step, `adopt_pages` for several wikis, `adopt_manifest`, the
  identity changes and their remedies, the manifestless-move and copied-wiki limits, the `ambiguous` key), `memory-tiers.md`
  (`set_wiki_identity`, `dedup_owner`, reserved identity tags) and CHANGELOG `[Unreleased]` (the upgrade step; the
  Windows regression under **Changed**).

## Constraints / What NOT to Build
- No change to the export or to deletion (D3). The ledger's file naming changes only by S6's migration. No new
  MCP tool; `wiki_import` gains two arguments and one response key.
- No migration pass over the store and no automatic adoption. Adoption happens at import, on `adopt_pages` or
  `adopt_manifest`.
- Release B 2c is a separate spec.

## Key Entities
- **`wiki-path:<hash>`, `wiki-id:<uuid>` tags:** the wiki an imported memory belongs to (S1). Absent on legacy
  memories (0.6 and earlier).
- **`adopt_legacy`:** the owner's per-call, wiki-wide assertion that each page's sole legacy record is this
  wiki's (S4).
- **`adopt_pages`:** the owner's per-call assertion, per `{path, ref_id}`, that this record is this page's (S4).
- **`adopt_manifest`:** the owner's per-call assertion that a wiki which gained a manifest is the same wiki (S6).
- **`ambiguous` report entry:** a page left untouched because a legacy record's ownership is unproven (S4), or
  because two records of this wiki dedup it (S2).

## Success Criteria
- **SC-1 (S2, S3):** two manifested wikis share a page path, and separately a `page_id`; their pages are
  identical, then different.
  - Importing B never supersedes, withdraws, deprecates or retags A's memory.
  - Each wiki has its own record with only its own identity tags; identical pages are two records.
  - B's `corrects` never treats A's correction as its own.
- **SC-2 (S4, migration):**
  - **A single-wiki 0.6 store, governed, upgraded with `adopt_legacy=True`:** every page with one legacy record
    adopts it (a current one `unchanged`, tagged, no new record; a changed page supersedes it with a tagged
    record); a page with two stays `ambiguous`; a second import without `adopt_legacy` behaves as before.
  - **The same store, selectively:** by default, the import writes nothing for those pages and reports
    them `ambiguous`; the store is unchanged. Naming one `{path, ref_id}` in `adopt_pages` adopts only that
    record; the others stay `ambiguous`. For a named page, a legacy record with the current
    `page_sha:` is adopted (`unchanged`, tagged, no new record), and a changed page supersedes its legacy record
    with a tagged record. A second import without `adopt_pages` then behaves as before for the adopted
    pages. An entry for a page that isn't `ambiguous` is reported `not ambiguous`, not applied.
  - **Candidate changed:** between the report and the adoption, the named record is `forget`-ed and another
    legacy record appears at the page; and separately a second legacy record appears. Each: `candidate changed`
    or `several legacy candidates`, nothing written, no record adopted.
  - **Owned plus legacy:** a page with one owned record and an unrelated legacy record at the same path is
    imported, superseded and deprecated as usual; the legacy record is unchanged and never reported.
  - **The same, ungoverned.**
  - **Two legacy candidates for one page**, by path and separately by `page_id`: even when the page is named, the
    import writes nothing for that page and reports `ambiguous` with both `ref_id`s; neither record changes.
  - **A legacy record whose bytes match this wiki's page** (same `page_sha:`): not adopted unless named.
  - **Duplicate owned records:** two live records of this wiki at one page, by key and separately by path, with
    the page already current (the early-return case) and with a changed page: `ambiguous` (`duplicate records`)
    with both `ref_id`s, nothing written. `retain` with two dedup hits raises `AmbiguousDedupError`.
- **SC-3 (S1, S6):**
  - The ungoverned and governed imports derive the same identity for one wiki.
  - A manifest that fails identity validation, on either path (a symlink, not an object, `manifest_version` 2, a
    non-UUID `wiki_id`), stops the import.
  - **Manifest added:** without `adopt_manifest`, `import_error` and nothing written, also when `adopt_pages` is
    given; with it, the memories gain the `wiki-id:` and the path-hash ledger is renamed.
  - **Ledger migration:** the `wiki_id` file already present (add, remove, re-add) and a failed rename each stop
    the import with `import_error`, nothing written, both files unchanged. An import interrupted right after
    the rename: the next import with `adopt_manifest=True` finishes the retag under the `wiki_id` ledger.
  - **Manifest removed, and `wiki_id` replaced:** `import_error` naming the id(s) and the remedy for each cause,
    nothing written.
  - **Manifested move:** with the page unchanged, it stays `unchanged` and its memory is retagged to the new
    path only; with a frontmatter-only edit, the revision dedups into the same record; with a content edit, it
    supersedes its own record. A retag interrupted halfway is completed by the next import.
  - **Old path reused** after a manifested move, by a manifested wiki and by a manifestless one: neither dedups
    into, supersedes nor retags the moved wiki's memories. Before the moved wiki is imported from its new path,
    the import at the old path stops with `import_error` naming its id.
- **SC-4 (S5):** `set_wiki_identity` changes only the identity tags and no other field. It refuses an unknown
  record, another project's, a non-wiki memory, and a different `wiki_id` from the one the record carries.
- **SC-5 (S7):** a corrupt ledger's rebuild ignores legacy and other wikis' memories.
- **SC-6:** fast suite green, coverage ≥ 80 percent, ruff and mypy clean.
- **SC-7 (S3, recovery and D4/D5):**
  - **Interrupted supersession,** governed and ungoverned: `_mark_superseded` fails right after the replacement
    is written. The next import completes the supersession from the replacement's `supersedes`, reports no
    `ambiguous` entry, and leaves one live record.
  - **D4 and D5 duplicates:** two live owned records for a superseded page's predecessor, for its successor, and
    for a deprecated page. Each: `ambiguous` (`duplicate records`), no store write, the ledger entry unchanged.
- **SC-8 (S8, concurrency; the lock mechanics are tested in the store-locks spec):**
  - **Concurrent adoption:** two processes import two wikis naming the same legacy `ref_id` in `adopt_pages`;
    exactly one adopts it, the other reports `candidate changed`.
  - **Concurrent same-wiki import,** ungoverned and governed: two processes, one new page; one record results.
  - **Reserved identity tags:** `retain` (library and MCP) with a `wiki-path:` or `wiki-id:` tag is refused. A
    move's retag then a dedup refresh, and a dedup refresh then the retag: either order leaves only the new
    `wiki-path:` and the one `wiki-id:`.
  - **`promote`:** promoting an imported wiki memory yields a copy with no wiki-import tag; a following import,
    governed and ungoverned, reports the page `unchanged` (or supersedes its own record), never `ambiguous`, and
    leaves the copy untouched.
  - **Non-POSIX** (`fcntl` patched away): an ordinary import, and imports with `adopt_legacy`, `adopt_pages`
    and `adopt_manifest`, governed and ungoverned, run and log one warning; a manifested move's retag runs.
  - **Ordinary retain onto a wiki memory (every platform):** `retain` (library and MCP) with content matching an
    imported wiki memory writes its own record and returns its new `ref_id`; the wiki memory's tags and fields
    are unchanged; a following import still reports the page `unchanged`. With several matches, a record
    without identity tags is the hit.

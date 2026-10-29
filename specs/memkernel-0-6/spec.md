# Spec: memkernel 0.6 — the Release B wiki bridge

Origin: memkernel #48 and its owner decisions (comments of 2026-10-24 and 2026-10-25), wiki-studio #38 and its Release B pitch.
Part 1 (US1–US2) was built against wiki-studio 0.6.0. Part 2a (US3–US4) is specified here against wiki-studio 0.7.0,
which also becomes the floor for both parts (FR-003 as amended 2026-10-27). Parts 2b and 2c are not specified yet.

## User Scenarios
- **US1 (part 1):** A memkernel agent exports long-term memories to a wiki that another wiki-studio writer is
  changing at the same time. Both writes land; neither is reverted; a failed export leaves wiki-studio's own
  rollback and receipt as the only recovery, and the export reports the failure.
- **US2 (part 1):** A maintainer can tell, from what memkernel records about an export, which wiki-studio
  proposal it was, so a replayed export is recognised and does not duplicate anything.
- **US3 (part 2a):** A curator approves wiki pages with wiki-studio. `wiki_import` brings in only the approved
  revision of each page: a draft, a page that declares itself approved, or a page edited after its approval is not
  imported, and an edited page keeps its last approved memory until it is approved again. Running the import twice
  adds nothing.
- **US4 (part 2a):** A curator fixes a wrong memory by approving a page whose `corrects:` key names it. After the
  import the wrong memory is no longer a current answer, its record is kept for provenance, and a reference the
  store does not know is reported, never dropped silently.
- **Part 2b (not specified yet):** withdrawal on supersession, deprecation and deletion, with a per-page sync
  state (pending, applied, failed) and a retry path.
- **Part 2c (not specified yet):** a governed configuration that refuses the ungated writer and checks the
  wiki's manifest policy; curation debt at session start.

## Requirements
- **FR-001 (no outer snapshot):** `WikiExporter`'s gated path MUST NOT snapshot or restore wiki files. On
  `GateError` or `OSError` from the gate it reports `gate_error` with the exception's message, counts the pages
  as skipped, and writes nothing itself. `_WikiSnapshot` is removed. A failure after FR-002's `api.init` (for
  example in `propose`) leaves the new `index.md` and `log.md` in place: a valid, empty scaffold, not removed.
  memkernel 0.5 left a fresh wiki with no files after a rejected export; the CHANGELOG says so, and the
  `gate_error` field's comment ("nothing was written") is corrected to "no page was written". The exceptions are
  FR-009's, where wiki-studio fails after its commit began: a commit reported as written, and an uncertain outcome
  (`uncertain_outcome`), where pages may be on disk.
- **FR-002 (scaffold through wiki-studio):** before proposing, the gated path MUST create a missing `index.md`
  and `log.md` with `api.init` (never overwrites; exclusive create), not with memkernel's own scaffold. The direct
  writer (no wiki-studio) keeps memkernel's scaffold. memkernel-0-5 SC-2's byte-identity therefore covers pages
  and appended index and log lines, not the scaffold of a new wiki; an existing wiki is unaffected. The difference
  is visible: wiki-studio 0.6.0's scaffold has `status: stable` and titles `Wiki` / `Wiki log`, memkernel's has
  `status: draft` and `Wiki Index` / `Wiki Edit Log`. The CHANGELOG says so, so a new wiki's `index.md` is not
  read as a bug.
- **FR-003 (version floor; amended 2026-10-27):** the `wiki` extra MUST require `wiki-studio >=0.7.0,<1`, one
  floor for export and import (owner decision 2026-10-27: `pyproject.toml` states one constraint for the extra, so
  two floors would admit a version the importer refuses). `gate_available()` MUST raise `GateError` (never fall
  back to unchecked writes) when an installed wiki-studio is older than 0.7.0 or lacks a call the bridge makes
  (`init`, `propose`, `promote`, `PageEdit`, `review_state`, `read_page`). ADR-010's addendum records the floor and
  why: 0.6.0 brought the scoped commit, exception rollback, receipts and the lock; 0.7.0 brings review state.
- **FR-004 (dev lock; amended 2026-10-27):** `poetry.lock` pins wiki-studio 0.7.0 for development and CI.
- **FR-005 (receipt reference):** a successful gated export MUST report, in new optional `ExportReport` fields
  defaulting to `None` (always `None` for the direct writer):
  - `proposal`: the proposal name memkernel passed to `api.propose`;
  - `submission_digest`: as the receipt records it;
  - `archived_dir`: `PromoteResult.archived_dir`, or `None` when wiki-studio committed the edits but its archive
    step failed (0.6.0 treats step 4 as housekeeping: `_archive_and_cleanup` catches `OSError` and returns
    `None`). memkernel then reports the export as promoted, not archived, and does not finish the archive itself;
    promoting the proposal directory again tries to finish it (amended 2026-10-28): wiki-studio applies nothing
    twice, but it may refuse and write nothing: with `payload_changed` if the proposal's files changed since, and,
    after a failure during its commit (receipt still `committing`), with `uncertain_outcome` (exit 10) if the wiki
    changed since, for example another writer appended to `index.md`;
  - `archive_hint`: set only in that case, and also logged as a warning. It says how to clear the state: the
    promote command, with the actual proposal directory and the `--root`, `--wiki-dir` and `--proposals-dir`
    memkernel used, all absolute (as wiki-studio's `WikiPaths` holds them), so it works from any directory. The
    hint presents the command as a recovery attempt, not a guaranteed finish: it says that wiki-studio applies
    nothing twice, that it may refuse and write nothing if the wiki or the proposal changed since, and that the
    wiki is then compared with the proposal's `receipt.json` by hand. The command runs through the interpreter
    memkernel runs on (`<sys.executable> -m wiki_studio promote …`), not a `wiki-studio` found on `PATH`, so it
    reaches the same wiki-studio the export used even when that is installed only in memkernel's environment.

  The receipt is read from where it actually is: `archived_dir/receipt.json` when archived (the directory may be
  `.applied/<name>-2/` and so on after a name clash, so the path is never rebuilt from the name), otherwise
  `PromoteResult.proposals_dir/receipt.json`. A missing or unreadable receipt after a successful promote sets
  `receipt_error` (new, optional) and never fails the export.
- **FR-006 (lock file):** the README's wiki section MUST tell users to ignore wiki-studio's advisory lock file
  (`<wiki-parent>/.<wiki-dir>.wiki-studio.lock`) where the wiki lives in a git checkout.
- **FR-007 (no update edits):** the bridge continues to emit only `create`, `append-index` and `append-log`
  edits; it never passes `allow_unguarded_updates`. (Recorded so a later change that adds updates must read the
  page and pass `base_sha256`.)
- **FR-008 (`wiki_export` response):** the MCP tool's JSON response MUST carry `proposal`, `submission_digest`
  and `archived_dir` for a gated export, `archive_hint` when `archived_dir` is null, `receipt_error` when the
  receipt was unreadable, and `uncertain_outcome` (FR-009) when the outcome is uncertain; keys absent otherwise, as `gate_error` is today. The tool's description is updated (it
  still says "wiki-studio >= 0.3" and that a rejected export "writes nothing"), and the CHANGELOG lists each
  added response key, as 0.5 did for `lint`, `lint_hint`, `lint_error` and `gate_error`. The tool count is
  unchanged.

- **FR-009 (committed, then failed; amended 2026-10-28):** wiki-studio can commit the pages and then raise, for
  example when it cannot rewrite its receipt as committed ("the edits were committed to the wiki … Promote the
  directory again to finish"). When the gate raises after `propose` returned a proposal directory, memkernel MUST
  classify the outcome from wiki-studio's own record, the receipt left in that directory, by the rule wiki-studio's
  own classifier applies to a `committing` receipt (0.6.0 `promoter._classify_committing`):
  - **No receipt:** not committed. wiki-studio writes the receipt before any wiki write, so a missing receipt is a
    `gate_error` (a refusal such as a create of an existing page), even when a page with identical bytes is on disk.
  - **A usable receipt:** readable, state `committing` or `committed`, and `planned_writes` a non-empty list in
    which every entry has a string `path`, a sha256 `post_sha256` and a null or sha256 `pre_sha256`, and which
    records every page memkernel created. Then:
    - *committed* when the state is `committing` and every planned write (the pages, `index.md` and `log.md`) is
      on disk at its `post_sha256`, or when the state is `committed` (wiki-studio writes it only after every write
      succeeded) and every page memkernel created is at its `post_sha256`;
    - *not committed* when the state is `committing` and every planned write is at its `pre_sha256` (absent when
      that is null): wiki-studio rolled back. A `gate_error`;
    - *uncertain* in every other case: for example a `committing` receipt whose pages are at their `post_sha256`
      while another planned write is not (the `index.md` write failed and the page's rollback failed too), a
      `committed` receipt whose pages are not all at their `post_sha256`, or a planned path outside the wiki
      directory or not a regular file.
  - **A receipt that cannot be used:** unreadable, in a state other than `committing` or `committed` (wiki-studio
    treats an unknown state as a corrupt receipt, not as "not committed"), or with `planned_writes` empty,
    malformed or missing one of memkernel's pages. `receipt_error` says why, and each page's bytes on disk are compared with the content
    memkernel proposed: all equal is *committed*, all absent is *not committed* (a `gate_error`), anything else is
    *uncertain*.

  *Committed* is reported as written and gated: the pages in `written`, `proposal`, `submission_digest` from the
  receipt when readable, `archived_dir` null, no `gate_error`, and `archive_hint` with the promote command (FR-005)
  that tries to finish it, preceded by wiki-studio's message; the hint is also logged as a warning.

  *Uncertain* MUST be reported neither as written nor as "no page was written": `written` is empty, the pages
  count as skipped, `gated` is false, `gate_error` carries wiki-studio's message, `proposal` is set, and a new
  optional `uncertain_outcome` (on `ExportReport` and in the `wiki_export` response) says that the outcome is
  uncertain, that memkernel's pages may be on disk (naming them), and that the wiki must be compared with the
  receipt by hand, giving the absolute path of the proposal's `receipt.json`, before exporting again. It is also
  logged as a warning. There is no `archive_hint`: wiki-studio would refuse that promote with
  `uncertain_outcome`. The `gate_error` field's comment becomes "no page was written, unless `uncertain_outcome` is
  set".

  memkernel never runs the promote again itself: that is the user's step.

### Part 2a (US3–US4)
- **FR-010 (governed import):** with wiki-studio ≥ 0.7.0 installed, `WikiImporter.import_pages()` MUST import a
  page only when `api.review_state` reports it `approved` and `api.read_page(rel).sha256` equals the state's
  `approved_sha256` (wiki-studio's consumer guide); every other page is skipped and listed in a new
  `ImportReport.not_approved` with its state and reason, so the report says why each page was skipped. The
  memory's content is taken from the same `read_page` result whose sha256 was checked; the file is not read
  again, so an edit between the check and the import can never be imported unapproved. memkernel
  never approves a page and never writes approval records.
- **FR-011 (without the extra, and below the floor):** with wiki-studio absent, the import keeps today's
  behaviour (it reads the page files; drafts included) and reports `governed: false`; the README and the tool
  description call it ungoverned. With wiki-studio installed but older than 0.7.0, broken, or lacking
  `review_state`, the import MUST import nothing and report `import_error` (never fall back to the ungoverned
  path). A governed import reports `governed: true`.
- **FR-012 (identity, revision, idempotency):** an imported memory keeps today's tags (`wiki`, `page:<slug>`,
  `page_type:<type>`) and `source` (the wiki-relative path), and gains `page_key:<page_key>` (wiki-studio's
  `page_id`, else the normalised path) and `page_sha:<approved_sha256>`. They are tags, stored in the existing
  comma-separated `tags` field, so no new metadata key is added and records written before 0.6 load unchanged
  (their tag lists simply lack them). A page whose approved revision already
  has a live memory with that `page_key` and `page_sha` is not imported again. A new approved revision supersedes
  the page's previous live memory (`supersedes`). A memory imported before 0.6 (no `page_key` tag) is matched by
  its `source`, the wiki-relative path, which is unique; never by `page:<slug>`, because slugs repeat across
  directories (`decisions/retry.md` and `workflows/retry.md`), which also fixes today's importer superseding
  one such page's memory with the other's.
- **FR-013 (stale and other non-approved states):** a page that is `stale`, `policy-changed`, `unapproved` or
  `superseded` is not imported, and its existing memory is left as it is (withdrawal is part 2b): an edited
  page keeps its last approved memory until it is approved again.
- **FR-014 (`corrects` grammar):** the frontmatter key `corrects` is memkernel's (wiki-studio ADR-0002 registers it
  and keeps it byte for byte). Its value is one line: a comma-separated list of tokens, each matching
  `[A-Za-z0-9_-]+` (memkernel `ref_id`s are such tokens), with optional whitespace around commas. An empty value,
  an empty token, or any other character makes the key invalid: the page is still imported, no correction is
  applied, and the page is listed in `ImportReport.invalid_corrects` with the reason. memkernel asks wiki-studio
  to record this grammar in ADR-0002; wiki-studio's fixture `tests/fixtures/corrects/multi-corrections.md` parses.
- **FR-015 (reconciliation):** after a page is imported under FR-010, each `corrects` token that names a live
  memory in this store that did not come from the wiki (no `wiki` tag: an originating raw memory, as #48 says) is
  marked superseded by the page's new memory (its `superseded_by` set; the record is kept, so its provenance
  remains). A token that names a memory imported from the wiki (another page's, or this page's own) is not
  applied: one source of truth per wiki fact, so a wrong wiki memory is fixed by correcting its page (owner
  decision 2026-10-27); it is listed in `ImportReport.unresolved` with the reason "correct the page instead". A
  token that names no memory in this store (unknown, or another project's), or one already superseded by a
  different memory, is listed in `ImportReport.unresolved` (page, token, reason) and never dropped silently.
  Reconciliation runs on every import of an approved page, including one whose revision is already current
  (amended 2026-10-27): corrections already applied are no-ops, and one left unresolved earlier is applied
  once it can be. A token already superseded
  by this page's memory is a no-op, so a second import changes nothing.
- **FR-016 (report and tool):** `ImportReport` gains `governed`, `unchanged` (approved pages whose revision is
  already the live memory; amended 2026-10-27, so `skipped` means only pages that cannot be imported),
  `not_approved`, `corrections` (page, ref_id
  applied), `unresolved`, `invalid_corrects` and `import_error`; the `wiki_import` response carries the same
  keys, present only when they apply, as `wiki_export` does. `WikiImporter` accepts an optional `project_root`
  (default the wiki directory's parent, as the exporter); the tool passes `MEMKERNEL_PROJECT_ROOT`. The MCP tool
  count is unchanged.
- **FR-017 (`MemoryService.supersede`, a core change):** the one new public method part 2a adds to `core/`.
  `supersede(ref_id, by_ref) -> bool` sets the durable `superseded_by` marker on `ref_id` (and its owned
  chunks), exactly as `retain(supersedes=...)` already does through `_mark_superseded`, and never edits the
  record's content, type, tier or any other field: replacements stay new records (CLAUDE.md), and this only
  links an existing record to its replacement. It returns `True` when it set the marker and `False` when
  `ref_id` was already superseded by `by_ref` (idempotent). It raises `ValueError` naming the reason, and changes
  nothing, when `ref_id` or `by_ref` is not a record in this store (an unknown or another project's reference),
  when they are equal, or when `ref_id` is already superseded by a different memory (never overwritten). The
  importer maps each refusal to `ImportReport.unresolved`. `docs/architecture/memory-tiers.md` is read before
  the change and updated: its supersession row (line 92) and API table (line 156) gain `supersede` and the
  `corrects` route.

## Constraints / What NOT to Build
- No held-lock route (owner decision 1: snapshot removal chosen). No change to wiki-studio.
- Nothing of part 2 (review state, `corrects`, withdrawal, governed mode) in part 1.
- No merge to `main` before the `v0.5.0` tag; no new runtime dependency (wiki-studio stays an optional extra).
  `core/` is unchanged in part 1; part 2a adds only `MemoryService.supersede` (FR-017).
- Part 2a builds nothing of 2b or 2c: no withdrawal, no sync ledger, no governed mode, no curation debt, no
  `page_id` assignment (`assign_page_ids` stays off), no approval by memkernel.

## Key Entities
- `ExportReport` (existing): gains `proposal`, `submission_digest`, `archived_dir`, `archive_hint`, `receipt_error` and `uncertain_outcome` (optional).
- `ImportReport` (existing): gains `governed`, `not_approved`, `corrections`, `unresolved`, `invalid_corrects`
  and `import_error` (part 2a).
- Imported wiki memory: tags `page_key:<page_key>` and `page_sha:<approved_sha256>` (part 2a).
- wiki-studio review state: `api.review_state(paths, pages=)` → `ReviewState(path, page_key, state, reason,
  live_sha256, approved_sha256, …)`; read-only for memkernel.
- wiki-studio receipt: `receipt.json` in `PromoteResult.archived_dir`, or in `PromoteResult.proposals_dir` when the
  archive step failed; read-only for memkernel.

## Success Criteria
- SC-1: The combined gate's compatibility test passes against wiki-studio 0.6.0: creates and appends through
  `api.propose` + `api.promote` land; a page created by another writer between planning and promote makes the
  export report the refusal (create of an existing page, exit 9) and retry nothing.
- SC-2: The concurrency test passes: a wiki-studio `promote` of another proposal running during a memkernel
  export; both land, neither is reverted, both `.applied/` archives exist.
- SC-3: A forced gate failure writes no page, changes no file another writer committed, and leaves at most the
  `index.md` and `log.md` that `api.init` created for a new wiki; the report carries `gate_error`.
- SC-4: With wiki-studio < 0.6.0 importable, a gated export is refused with `GateError` in the report and writes
  nothing.
- SC-5: Fast suite green, coverage ≥ 80 percent, ruff and mypy clean; nine MCP tools unchanged.
- SC-6: With wiki-studio's archive step forced to fail after the commit, the export's pages land, the report has
  `archived_dir = None`, `proposal` and `submission_digest` read from the receipt left in the proposals directory,
  `archive_hint` naming that directory, and no `gate_error`. Running the hint's command exactly as given (through
  `sys.executable -m wiki_studio`) then archives the proposal and changes no wiki page. The `wiki_export` response
  carries the same keys (FR-008).
- SC-7 (amended 2026-10-28): With wiki-studio forced to fail after its commit (the receipt rewrite as
  committed), the export reports the page as written and gated, `archived_dir = None`, no `gate_error`, and an
  `archive_hint` whose command, run as given, finishes the promotion without changing the page; if another writer
  appends to `index.md` first, the same command is refused with `uncertain_outcome` (exit 10) and changes no file,
  and the hint says it may be. With the receipt present but unreadable, or with `planned_writes` empty, not a
  list, holding a malformed entry or missing the page, the content check reports the page as written and
  `receipt_error` is set; so does a receipt in an unknown state. With the page written, the `index.md` write failed and the page's rollback failed (a
  `committing` receipt, page at `post_sha256`, index not), the export reports `uncertain_outcome` naming the page
  and the `receipt.json` path, `written = []`, `gate_error` set and no `archive_hint`. A refusal before any
  receipt (another export created the same page with identical bytes) and a rolled-back failure report `gate_error` without `uncertain_outcome`.
- SC-8 (part 2a): wiki-studio's `tests/integration/test_release_b_loop.py` passes against this memkernel, run
  from a named wiki-studio commit: the first commit on wiki-studio `main` that resolves wiki-studio#53 (test 4's
  use of `ref_id` and `include_superseded=True`); until then, v0.7.0's file for tests 1–3 and the two retry
  tests. The code PR records the wiki-studio commit SHA and the result. memkernel's CI does not run this test
  (it lives in wiki-studio's repository); wiki-studio's "memkernel Release B loop" job is the standing check,
  once it pins a memkernel commit that contains part 2a.
- SC-9 (part 2a): memkernel's own tests cover, against the real wiki-studio 0.7.0: a draft and a self-declared
  approval are not imported; a stale page keeps its last approved memory and is imported once re-approved; a live
  sha256 that differs from `approved_sha256` is skipped; the import run twice adds no memory; `corrects` with
  several tokens, an unknown token, another project's token, a token naming another page's wiki memory
  (unresolved, "correct the page instead"), an invalid value, and a second import; without the
  extra the import is ungoverned and says so; below the floor it imports nothing and reports `import_error`; an
  import over a store written before 0.6 (wiki memories without `page_key`/`page_sha`) matches them by `source`
  and supersedes rather than duplicates them, and two pages with the same slug in different directories keep
  separate memories; `supersede`'s refusals (unknown, another project,
  self, already superseded by another) and its idempotence.


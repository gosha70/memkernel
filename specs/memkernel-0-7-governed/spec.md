# Spec: memkernel 0.7, Release B part 2c: governed mode and curation debt (#48)

Origin: #48 and wiki-studio's Release B pitch, its memkernel counterpart (`origin/2026-11-03-part-2c.md`). Facts
are in `plan.md`.

## User Scenarios
- **US1:** a team that curates its wiki under wiki-studio's approval wants memkernel never to write or read the
  wiki around the gate. With `MEMKERNEL_WIKI_MODE=governed`, an export that cannot go through the gate, or an
  import that cannot read wiki-studio's review state, writes nothing and says why.
- **US2:** an independent deployment without wiki-studio wants that to be a named choice, not an accident of what
  is installed: `MEMKERNEL_WIKI_MODE=ungated`, reported as such.
- **US3:** at session start the agent sees what in the wiki needs a curator (unapproved and stale pages, failed
  sync actions), in a few lines, without the block growing past its 9,000 characters.
- **US4:** a curator reviews exports in small batches, and each exported page says which revision of its source
  file it was grounded at.

## Decisions (confirmed by the owner on 2026-11-04; revised after review)
**G1. One setting picks the wiki mode: `MEMKERNEL_WIKI_MODE` = `auto` (default) | `governed` | `ungated`.**
- **`auto`** is today's behavior, unchanged: the gate and the governed import when wiki-studio >= 0.7.0 is
  installed, the direct writer and the file-reading import when it is absent, a refusal when it is installed but
  broken or too old.
- **`governed`** requires, before any write or read of pages, for both `wiki_export` and `wiki_import`:
  - wiki-studio >= 0.7.0 installed and working (`gate_available()` returns the API);
  - `api.info`'s `capabilities` include every capability the bridge uses, a named constant
    (`GOVERNED_CAPABILITIES`): `wiki-lock`, `receipts`, `root-manifest`, `page-id` (G5), `approval-record`,
    `superseded-by`, `findings`. A missing one refuses, naming it; the constant changes only with the wiki-studio
    floor;
  - the wiki's manifest `mode` is `governed` (policy `approval_required: true`). A `managed` wiki (a manifest,
    default policy) and a `legacy` one (no manifest) are refused, with the remedy (`wiki-studio init`, then set
    `approval_required: true` in the manifest's policy);
  - no schema drift (`api.info`'s `warnings` empty), which wiki-studio would refuse later anyway.

  These checks are the **governed preflight**, one function both directions and the curation debt (G2) call.
  Any failure: the export reports `gate_error` and commits no drafted page (the preflight runs before
  `api.init`, so a preflight refusal writes nothing at all); the import reports `import_error` and writes nothing
  to the memory store or the sync ledger.
- **What a gate failure after the preflight leaves.** The gated export runs `api.init` before `propose` when
  `index.md` or `log.md` is missing (memkernel-0-6 FR-002), and memkernel keeps no outer rollback (memkernel-0-6
  FR-001). So a rejection after that point commits no drafted page but may leave the scaffold `index.md` and
  `log.md` that `init` created. The README says so. The direct writer is never used, so `update_index=False` is refused too.
- **`ungated`** never loads wiki-studio: no `load_studio`, gate, lint, review state or findings call, whatever
  is installed. The direct export today calls `lint_wiki` after writing, which loads wiki-studio; in `ungated`
  mode it is skipped, and `lint` is reported as `null` with `lint_hint` naming the mode.
- Every `wiki_export` and `wiki_import` response gains `"mode"`, the path that ran (`gated` through
  wiki-studio's gate and review state, `ungated` around it), and `"configured_mode"`, the setting
  (`auto`, `governed`, `ungated`). `gated` is not wiki-studio's `governed` wiki mode: in `auto`, a `managed` wiki
  goes through the gate as today, and the strict preflight applies only when `configured_mode` is `governed`.
- **Rejected:** a per-call argument. The mode is a property of the deployment, set where the MCP server or the
  library is configured; an agent that calls the tools could otherwise pass `ungated` around the gate. An agent
  that can change the server's environment is outside this boundary, as for every other setting.

**G2. Curation debt at session start.**
- **When:** the full session-start block (`startup`, `clear`, and no source), not `compact`, `resume` or `fork`;
  only when `MEMKERNEL_WIKI_DIR` is set, the configured mode is not `ungated`, and wiki-studio is available. In
  `auto`, a `managed` or `legacy` wiki, a drifted one and one missing a capability are read as today's gated path
  reads them (wiki-studio itself refuses drift only on a governed wiki). When `configured_mode` is
  `governed`, only after the governed preflight (G1) passes: a `managed`, `legacy`, drifted or capability-incomplete
  wiki is never read; the section is then the one unavailable line, naming the refusal.
- **What:** a `### Curation debt` section:
  - one line of the nonzero counts from `api.findings` (`counts`), in memkernel's own order
    (`CURATION_KIND_ORDER`, a constant: the review kinds `unapproved`, `approval-stale`,
    `approval-policy-changed`, `superseded-still-indexed`, then `stale-claim`, `weak-orphan`,
    `missing-cross-link`, `avoid-format`, `no-page-id`; a kind it does not know follows, by name), never
    wiki-studio's dictionary order, plus memkernel's own: the sync ledger's unfinished entries for this wiki
    (`pending`, `failed`);
  - up to `CURATION_DEBT_MAX_LINES = 3` example lines (`- <kind>: <page>`): findings whose kind is a review kind
    first, then the rest, both in `CURATION_KIND_ORDER`;
  - one hint: run `wiki-studio findings` for the full list.

  No debt: no section. A failure of `findings` gives one line, `Curation debt unavailable: <reason>`; the hook
  never fails because of it.
- **Budget (the reviewer's recommendation, 2026-11-03):** the section is at most `CURATION_DEBT_BUDGET = 500`
  characters, and the context share lends only what the section actually uses: context gets
  `CONTEXT_BUDGET - len(rendered section)`. No debt, no section: context keeps its full 2,500. `TOTAL_BUDGET`
  stays 9,000, as `lifecycle.py` requires.
- **The ledger is read, never touched.** A new read-only snapshot in `ledger.py` gives the unfinished counts. It
  never creates, renames or saves a ledger file (it may create the empty lock file, as `run()` does).
  `SyncLedger.run()` is not used: it moves a corrupt ledger aside and
  saves a new one, which would destroy the evidence the next import recovers from.
  - **On disk** (in the child, below): an import holds the ledger's exclusive lock while it changes its entries
    and saves only at the end, so an unlocked read could see a complete but stale file. The snapshot therefore
    takes the **same lock file** `run()` takes, `<key>.json.lock`, with a **non-blocking shared** `flock`;
    contention gives the unavailable line. The child closes that descriptor in a `finally`, and its exit, a kill
    included, releases the lock in any case.
    - **The linearization point is the ledger directory's check.** If the project's ledger directory
      (`<state>/wiki-sync/<project>/`) does not exist, no import has ever written a ledger: the counts are zero,
      and an import that creates it later started after the snapshot. If it exists, the snapshot opens the lock
      file with create-if-missing, exactly as `run()` does (an empty lock file is not ledger data), and takes the
      shared lock before reading `<key>.json`. So an import holding the lock, its first one included, always
      gives the unavailable line; there is no window between a check and a read. The snapshot creates nothing
      else and never touches `<key>.json`.
    - Without `fcntl` the read is unlocked, as every other ledger access is there (memkernel-0-7-store-locks L4).
  - **In memory** (an in-memory store's ledgers are process-global dictionaries, `ledger.py:42`, invisible to a
    child), a process-local `threading.Lock` per ledger, new, is held by `SyncLedger.run()` for its whole run and
    taken by the snapshot **non-blockingly** in the parent: contention gives the unavailable line, and the
    snapshot copies the counts under it. Each ledger's lock is created once, under one module-level guard, so two
    threads never install two locks for one ledger. The lock is not re-entrant, and `run()` never calls the
    snapshot. This is the only part of the debt that runs in the parent: it never waits, and it observes the same
    monotonic deadline while it copies (checked every `CURATION_DEBT_DEADLINE_CHECK_EVERY = 100` entries); past
    the deadline it releases the lock and gives the unavailable line (`timed out`).
  - A missing ledger counts nothing; a corrupt one gives the unavailable line.
- **A hard time bound, by a process boundary.** Everything else runs in one child process (`multiprocessing`,
  spawn context): detecting wiki-studio (`gate_available`), in `governed` the preflight, `findings`, and the
  on-disk ledger snapshot. The parent only checks the settings (wiki directory set, mode not `ungated`) before
  starting it.
  - **One deadline.** The parent takes a monotonic deadline, `CURATION_DEBT_TIMEOUT_SECONDS = 2.0`, once
    `Process.start()` returns, before the in-memory snapshot (amended, below). A start that raises is the unavailable line, and the cleanup below still runs (both pipe
    ends closed; a process object that reports itself alive goes through the bounded reap), so a partial start
    leaks nothing. **Amended during the build (2026-11-04, the owner's decision):** `Process.start()` runs on the
    calling thread and cannot be interrupted, so the deadline is taken once it returns: the 2.5 seconds bound the
    check, not a fork or exec the operating system holds up. Allocating the pipe and every cleanup step are inside
    the no-raise boundary, and each cleanup step runs whatever the one before it did.
  - **The result** is one plain, bounded dict (the counts as integers, at most `CURATION_DEBT_MAX_LINES` example
    pairs, each string cut to `CURATION_DEBT_FIELD_CHARS = 200`, or an error string), sent over a one-way
    `multiprocessing.Pipe(duplex=False)`, never a `Queue`. The parent keeps the read end and closes its copy of
    the write end right after the start; the child closes its copy of the read end first and its write end in a
    `finally`, so the parent sees EOF as soon as the child ends. The parent waits with `poll(remaining)` and
    receives before joining, so a large result can never block a join. EOF (the child died or raised before
    sending) is the unavailable line.
  - **Every wait is bounded, with the grace split in two.** Past the deadline: `terminate()`, then
    `join(CURATION_DEBT_TERM_GRACE_SECONDS)` (0.3); if the child is still alive, `kill()`, then
    `join(CURATION_DEBT_KILL_GRACE_SECONDS)` (0.2). Each interval is its own, so the post-kill reap always has its
    0.2 seconds. The debt's total time once the child has started is at most 2.0 + 0.3 + 0.2 = 2.5 seconds, the in-memory snapshot
    included, whatever the child does. A child still alive after that is left to the operating system, reported
    as the unavailable line (`not reaped`), and not closed (`Process.close()` refuses a live process).
  - **Cleanup on every path:** both pipe ends are closed in a `finally`; a reaped child gets `Process.close()`. So
    repeated session starts in one long-lived process accumulate no children, pipes or sentinels.
  - The build measures the time on a 200-page wiki, the child's start-up included, and reports it in the PR.

**G3. Bounded export batches.** A new setting `MEMKERNEL_WIKI_EXPORT_BATCH` (default 10; 0 means no limit):
`wiki_export` writes at most that many new pages per call: by the memory's `importance`, highest first, then by
`timestamp`, oldest first, then by `ref_id`, so the order is deterministic.
The response gains `remaining`: the eligible memories still without a page after this call's successful writes.
A rejected batch writes none, so all remain: a 10-page batch from 12 that the gate rejects reports
`remaining: 12`. A `governed` refusal by the preflight reads nothing of the wiki, so `remaining` is `null` there
too (amended during the build; confirmed by the owner on 2026-11-04). A negative batch is refused as a setting. When the gate's outcome is
uncertain (`uncertain_outcome` is set, `GateUncertainError`: some
pages may be on disk), `remaining` is `null`: unknown, so nothing invites a blind retry; the
`uncertain_outcome` hint says how to reconcile. One reviewable batch per curator
pass, and a small gate proposal.

**G4. Source revision and content hash on exported pages.**
- A `path:` source gains `sha:`, the git commit the page is grounded at, as wiki-studio's citation rules define it
  (`git log -1 --format=%h -- <path>`), when the file is tracked and unmodified: `git status --porcelain -- <path>`
  prints nothing (no staged or unstaged change). A modified, staged or untracked file, a path git reports no commit
  for (outside the repository, or inside a submodule), or no git, gets no `sha:`: no commit grounds it. A file
  counts as tracked only when the project's own `git ls-files -- <path>`, run from the project root, lists exactly
  that path (equality, not a prefix or a pattern): a
  file inside a submodule is not listed by the superproject, so it never takes the submodule's commit. git is run as a subprocess, read-only, with a
  short timeout; no new dependency.
- The page gains `memkernel_sha256: <the memory's content hash>`, memkernel's own key beside `memkernel_ref` and
  `memory_type`, so a curator, or a later revalidation, can tell which revision of the memory the page drafted.
- **Rejected:** a `sha256:` key inside a source entry. wiki-studio's citation rules do not define it.

**G5. `page_id` on created pages.** The gated export passes `assign_page_ids=True` to `api.propose`, so every page
memkernel creates carries wiki-studio's stable `page_id`. The import keys pages by `page_key`, which is the
`page_id` when present.
- **Amended during the build (2026-11-04; confirmed by the owner on 2026-11-04):** this spec said a later rename already kept the page's memory. Against the real wiki-studio it
  did not: a renamed page keeps its content, so the import found no dedup hit at the new path and wrote a second
  live memory. The import now also supersedes when the page's previous memory, found by `page_key`, is at another
  path, so a rename leaves one live memory with its history. At the owner's request (2026-11-04) the import also
  skips its "already current" early return when that memory's `source` is another path: a page moved with
  identical bytes (wiki-studio's approval follows the `page_id` and the bytes, so the moved page is approved
  without a new approval) gets its record at the new path, and the old path no longer finds it. A new page at the
  old path therefore never takes the moved page's memory; wiki-studio itself refuses to approve one while the
  moved page keeps the same slug. One more existing assertion changed with it (confirmed by the owner on 2026-11-04):
  `test_a_rename_that_kept_its_page_id_is_not_a_deletion` asserted the memory stayed at the old path; it now asserts
  the one live memory is at the new path and supersedes the old record, and still that nothing is withdrawn.

**G6. The gate checklist items only the bridge can tick.**
- **Receipts:** consumed since 0.6 (`proposal`, `submission_digest`, `archived_dir`); nothing to build.
- **The lock file:** the README tells a project whose wiki is in git to ignore `.*.wiki-studio.lock` beside the
  wiki directory; memkernel creates no lock file of its own there.
- **`hash_recipe`:** memkernel reads no ingest log, so there is no consumer; the README and #48 say so.

## Requirements
- **FR-001 (G1):** `MEMKERNEL_WIKI_MODE` with `auto`, `governed`, `ungated`; the governed preflight before any
  page write or read, on export and import; `ungated` never touching wiki-studio; the `mode` and
  `configured_mode` response keys; documented in the README configuration table.
- **FR-002 (G2):** the curation debt section after the preflight in `governed`, `CURATION_KIND_ORDER`, its budget
  lent from the context share by its rendered length, the read-only ledger snapshot, the time bound, its
  unavailable line.
- **FR-003 (G3):** `MEMKERNEL_WIKI_EXPORT_BATCH` and `remaining`.
- **FR-004 (G4):** `sha:` on a clean tracked `path:` source; `memkernel_sha256` on every exported page.
- **FR-005 (G5):** `assign_page_ids=True` on gated exports.
- **FR-006 (G6):** README notes for the lock file and `hash_recipe`; a comment on #48 ticking the items, on the
  owner's go.
- **FR-007:** README, CHANGELOG `[Unreleased]`.

## Constraints / What NOT to Build
- No change to what `auto` does today; no change to the import's identity rules (memkernel-0-7-wiki-scope).
- No new MCP tool and no new dependency. git is optional.
- No release, and not the Release B exit run (one correction loop on clean installs): a separate step.

## Key Entities
- **Wiki mode:** `auto`, `governed`, `ungated` (G1).
- **Curation debt:** wiki-studio's findings counts plus memkernel's unfinished sync actions (G2).
- **Export batch:** at most `MEMKERNEL_WIKI_EXPORT_BATCH` new pages per export (G3).

## Success Criteria
- **SC-1 (G1):**
  - `governed`: an export and an import each refuse, writing nothing, with wiki-studio absent, below 0.7.0, a
    capability missing (patched `info`, `page-id` among the cases), a `managed` and a `legacy` wiki, and schema
    drift; with a governed wiki both run through the gate, and `update_index=False` is refused.
  - A gate rejection after `api.init` (patched `propose`): no drafted page is committed, the scaffold
    `index.md` and `log.md` remain, and the report says the export was rejected.
  - `ungated`: with wiki-studio installed but `load_studio`, `gate_available`, `lint_wiki`, `review_pages` and
    `findings` patched to raise, the export writes directly, the import reads files, the session-start block has
    no curation debt, and the responses say `"mode": "ungated", "configured_mode": "ungated"`.
  - `auto`: with wiki-studio present the responses say `"mode": "gated", "configured_mode": "auto"`, and a
    `managed` wiki is exported, imported and given a curation debt section as today's gated path allows; with it
    absent, `"mode": "ungated", "configured_mode": "auto"`. Every existing test passes; **amended during the build
    (2026-11-04; confirmed by the owner on 2026-11-04):** three test helpers changed because gated pages now carry a
    `page_id` (G5), with no assertion weakened: a copied twin page drops its `page_id`, a hand-made duplicate record
    uses the page's key, and the gated-versus-direct comparison ignores the `page_id` line and asserts it is there.
- **SC-2 (G2):**
  - a wiki with an unapproved and a stale page, and a failed ledger entry: the startup block shows one counts
    line, the examples and the hint, and stays under 9,000 characters with every other section full; the context
    share shrinks by the section's length only;
  - no debt: no section, and the context share is the full 2,500;
  - counts given in a shuffled order render in `CURATION_KIND_ORDER`;
  - `governed` with a `managed` wiki: `findings` is never called, and the section is the unavailable line;
  - `findings` raising, a corrupt ledger, and an in-memory ledger whose lock an import holds (a patched `run()`
    blocking on an event, so the contention is deterministic): the one unavailable
    line each; the ledger file is byte for byte unchanged and no ledger file is created or renamed;
  - the child's paths, each through a test hook the child imports (a spawned child does not see the parent's
    patches): success; an exception before sending, and an exit without sending (EOF); `findings` slower than the
    deadline; a send patched to sleep past the deadline; a child whose `SIGTERM` handler does nothing (killable by
    `SIGKILL`, so the `kill()` fallback is what ends it). Each: the right section or unavailable line, within
    2.5 seconds. A child that survives `SIGKILL` (an uninterruptible sleep) cannot be bounded from user space; it
    is reported `not reaped` and is out of the tests' reach;
  - a `Process.start()` that raises: the unavailable line;
  - an on-disk ledger whose exclusive lock an import holds (in another process), including a first import that
    created the lock file itself: the unavailable line, `<key>.json` unchanged; no ledger directory: zero counts,
    and nothing created; a ledger directory without this wiki's lock file: the lock file created empty and
    `<key>.json`, if any, read under the shared lock;
  - an in-memory ledger large enough, or a copy slowed by a test hook, to pass the deadline: the unavailable line
    (`timed out`), the lock released;
  - in a process that stays alive afterward, 20 session starts in a row, half of them timing out (killable
    children): no child left running (`multiprocessing.active_children()` empty), the process's open descriptors
    (`/dev/fd`, POSIX only, as CI is) back to their count before, and an import taking the ledger at once;
  - `compact`, `resume`, `fork` and `ungated`: no section;
  - the measured time on a 200-page wiki is in the PR.
- **SC-3 (G3):** with 12 exportable memories and the default batch, an export writes 10 (the most important first,
  ties by age, then `ref_id`) and reports `remaining: 2`; the next writes 2 and reports 0; batch 0 writes 12; a
  gate-rejected batch of 10 reports `remaining: 12`; an uncertain outcome (patched `GateUncertainError` after some
  pages are written) reports `remaining: null` with `uncertain_outcome`.
- **SC-4 (G4):** a clean tracked source gets the commit `sha:`; a modified, an untracked and a no-git source get
  none; every page carries `memkernel_sha256`; the pages pass the gate.
- **SC-5 (G5):** a gated export's pages carry a `page_id`; renaming one keeps its memory on the next import; in
  `governed`, a wiki-studio without `page-id` is refused (SC-1).
- **SC-6:** fast suite green, coverage >= 80 percent, ruff and mypy clean.

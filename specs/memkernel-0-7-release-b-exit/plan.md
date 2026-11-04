---
feature_id: memkernel-0-7-release-b-exit
spec_mode: lightweight
status: draft
date: 2026-11-04
collaboration_mode: single
origin:
  issue: gosha70/memkernel#48
  urls:
    - https://github.com/gosha70/memkernel/issues/48
    - https://github.com/gosha70/wiki-studio/issues/38
    - https://github.com/gosha70/wiki-studio/blob/main/docs/demo-correction-loop.md
  transcripts:
    - specs/memkernel-0-7-release-b-exit/origin/2026-11-04-exit-run.md
  origin_claim: |
    memkernel #48: "Exit evidence for Release B as a whole: one complete correction loop (retain, export,
    review, import, correct, next-session recall) on clean installs with compatible versions, surviving
    retries." The owner (2026-11-04): "plan the Release B exit run for review."
---

# Plan: the Release B exit run

## What the exit evidence must show (#48)
One complete correction loop: retain, export, review, import, correct, next-session recall. It runs on clean
installs of released, compatible versions, and it survives retries. This plan says how memkernel records that
run, and what it adds to the evidence that already exists.

## What exists, and the gap
- **wiki-studio's recorded run** (wiki-studio 0.8.1 + memkernel 0.6.0) shows correction by replacement on clean
  installs. It was run once and never retried. It predates memkernel 0.7, so it shows none of the following:
  - withdrawal of a deprecated, deleted or superseded page (2b);
  - the wiki's identity on its memories, and the store locks;
  - governed mode, the curation debt at session start, or export batches (2c).
- **SC-8** passes 6/6 against memkernel `main`, including wiki-studio's retry property. But it runs from source
  trees, not from clean installs of released packages, and it doesn't cover memkernel's own retries: an import
  stopped between the store write and the ledger, and a second import running at the same time.

The exit run closes that gap: the whole loop, on released wheels, in `governed` mode, with the retries injected
and each one converging.

## Proposed run
**Versions.** memkernel 0.7.0 and wiki-studio from PyPI, each wheel checked against the sha256 PyPI
publishes:
- memkernel 0.7.0, so 0.7.0 is released first;
- wiki-studio's newest release, 0.8.1, or 0.8.2 if it is out by then.

Python 3.11, a fresh virtual environment, and the embedding model pinned to one revision (wiki-studio's recorder
pins `1110a243…`). Only base wiki-studio: memkernel needs `mcp<2` (#95), and the run needs no MCP server.

**Setup.** One project and one persisted store, under one work directory:
- a governed wiki: `wiki-studio init`, then `approval_required: true`;
- `MEMKERNEL_WIKI_MODE=governed`;
- `MEMKERNEL_WIKI_EXPORT_BATCH` left at its default of 10.

**Sessions.** Each is a separate process, calling what memkernel's MCP tools and session hooks call.
1. **Session 1:**
   - retain a wrong decision, plus three memories to withdraw later;
   - `recall` returns the wrong rule;
   - export them through the gate (one batch, drafts) and check that `remaining` is 0;
   - the session-start block shows the curation debt for the unapproved drafts.
2. **Curator** (wiki-studio CLI, as in wiki-studio's demo):
   - correct the wrong page: replace the rule, `status: stable`, `corrects: <memkernel_ref>`, a guarded update
     with `--promote`, then `approve`;
   - deprecate one page, and approve that revision;
   - delete one page;
   - supersede one page by a successor page;
   - approve the remaining stable pages.
3. **Session 2:**
   - the governed import reports the correction, the withdrawals (deprecated, deleted) and the supersession;
   - the sync ledger holds no unfinished entry.
4. **Session 3, the next session:**
   - the session-start block injects no wrong rule;
   - `recall` of the question returns the corrected page, with its `page_sha:` equal to `approved_sha256`, the
     receipt's `submission_digest`, and the approval's `approver`;
   - the wrong, deprecated, deleted and superseded memories are absent from current answers and still kept,
     visible with `include_superseded=True`. memkernel withdraws a deleted page's memory and keeps its record
     (memkernel-0-7 D3), the same as for the other three;
   - the curation debt shows no unapproved page.

**Retries.** Each session is a process that `run.py` starts (`run.py session-2 …`); that process imports
memkernel and installs any wrapper a retry needs before it calls the import. Faults are injected only that way,
never by patching the installed packages' files. Each retry must converge. The expected end state is written
into the script: which pages are live, and which records are withdrawn or superseded. It is not taken from a
second run. The run checks:
- the same live pages, live memories (by page key and content) and withdrawn or superseded records as a
  fault-free run;
- no page key with two live memories;
- no duplicate page or receipt;
- no unfinished ledger entry.

`ref_id`s and timestamps differ between runs, so the run compares this summary, not a byte hash.
- **R1, an interrupted promote:** a promote interrupted after its commit resolves from its receipt (wiki-studio's
  rule, as in SC-8).
- **R2, an interrupted supersession** (wiki-scope S3; the owner's choice, 2026-11-04):
  - after session 2, the curator edits one page that is already imported, and approves the new revision;
  - the next import writes that page's replacement memory, then must mark its predecessor `superseded_by` it;
  - the run kills that import process (`os._exit`, so no `finally` saves anything) between those two steps.
    It does this by wrapping `MemoryService._mark_superseded` in the run's own process, and only for that
    predecessor's `ref_id`, so the kill never falls on another supersession and never depends on timing;
  - after the kill, the run checks that the predecessor and its replacement are both live. Chroma commits each
    write to SQLite before returning, but if the kill ever lost the replacement's write, this check fails the
    run visibly rather than letting the retry pass by accident;
  - re-running the import must complete the supersession from the replacement's `supersedes` (wiki-scope
    `_recover`), leaving one live memory for the page and the predecessor kept as superseded.

  `_mark_superseded` is a private method, so the run is tied to the memkernel 0.7.x it records. memkernel's
  `test_an_interrupted_supersession_is_completed_by_the_next_import` makes the same cut, with an exception
  instead of a kill.
- **R3, everything twice:** export and import each run a second time and change nothing.
- **R4, two imports at once:** two session-2 processes share one store.
  - In the first, a wrapper around `MemoryService.retain` pauses on a marker file after its first write.
  - The second then starts. Right before it calls the import, it writes a marker that it reached the import. A
    wrapper in it records the time of its first write.
  - The run releases the first only after the second's marker exists, plus a fixed hold, so the second is
    known to be waiting on the lock during that hold (the owner's amendment, 2026-11-04).
  - The check is that the second's first write comes after the release, which shows the store's import lock
    serialized the two rather than luck. That lock is
  `exclusive("wiki-import")`, held from the identity checks to the last write, alongside the ledger's file lock.
  memkernel's `tests/integration/test_wiki_scope_processes.py` steers processes the same way. Like R2, R4
  depends on how 0.7.x implements this (the import lock and the ledger's lock), so it is tied to the release it
  records. Both must succeed, the second finding everything current, and the convergence checks above
  must pass, the ledger's included.

**Checks.** Each one is named in the output, as wiki-studio's demo does, and the run stops at the first one
that fails. The manifest of a failed attempt lists every check that ran, with its result, the failing one
included.

## Recording
The recording follows wiki-studio's protocol (`examples/correction-loop/README.md`):
- the script and the recorder are committed first;
- the run starts from a clean tree, recorded by its full SHA, and works only from that extracted commit;
- the wheels are downloaded and their sha256 checked against PyPI;
- `pip freeze` is recorded;
- the run happens once and is never retried;
- a failed attempt is kept, and a second attempt is a new directory;
- the run directory is committed alone, in its own commit, and never edited.

The manifest records:
- the run script's commit, by its full SHA;
- each wheel's file name and sha256, checked against PyPI;
- the embedding revision;
- `pip freeze`;
- every check with its result;
- the convergence summary.

The protocol README names the wiki-studio commit whose `examples/correction-loop/README.md` it follows, so
drift between the two is visible. The owner runs the recorded run and commits its directory.

If the recorded run finds a defect in 0.7.0, that attempt is kept as it is. The fix ships as 0.7.1, and a new
attempt is recorded in a new directory that names 0.7.1. #48's exit evidence is the first released 0.7.x that
passes, paired with the wiki-studio release it ran with. "Never retried" means an attempt is never re-run in
place. Most defects should surface earlier, because the informational workflow (E5) runs the same script on
every pull request before the release.

## The upgrade path (0.6 → 0.7): where adoption is tested
0.7 gives every imported memory its wiki's identity. A store imported by 0.6 has none, so its first 0.7 import
lists those pages under `ambiguous` and writes nothing for them until the owner adopts them (`adopt_legacy`,
`adopt_pages`, `adopt_manifest`; the CHANGELOG's upgrade step). Adoption is tested only with a simulated 0.6
store:
- **`tests/integration/test_wiki_scope.py`:**
  - `_make_legacy` strips a record's identity tags, which is what a 0.6 import left;
  - the adoption tests cover a legacy store writing nothing until adopted, `adopt_pages` adopting exactly the
    named record, a named record that changed meanwhile, an owned record next to a legacy one, the ungoverned
    import, and a manifest added after the fact (`adopt_manifest`, with the ledger moved).
- **`tests/integration/test_wiki_withdrawal.py`** (`test_a_legacy_memory_is_never_withdrawn_as_deleted`) and
  **`tests/integration/test_wiki_scope_processes.py`** (two wikis adopting one record at once).
- **`tests/e2e/test_mcp_roundtrip.py`** (`test_wiki_import_reports_ambiguous_pages_and_adopts_on_request`), through
  the MCP tool.
- **`tests/integration/test_wiki_import_governed.py`** (`test_a_memory_imported_before_0_6_is_matched_by_its_path`),
  for a store from before 0.6.

No test opens a store that memkernel 0.6.0 itself wrote, and the run above leaves adoption out (E3). That gap
is the subject of E7.

## Decisions for the owner
Confirmed by the owner on 2026-11-04: E1–E6 as recommended, E7 as a separate upgrade run, R2 at the
interrupted supersession, and E5 with a path filter.

- **E1. Order.** Release memkernel 0.7.0 first, so the run uses released wheels as #48 asks: script PR, then the
  0.7.0 release, then the recorded run. Recommended. The alternative records against a built wheel of `main`,
  which would not be "released".
- **E2. Where it lives.** memkernel's `eval/release-b-exit/` (`run.py`, `record.py`, `runs/`). Recommended,
  because #48 is memkernel's tracker and the run covers memkernel 0.7. The alternative extends wiki-studio's
  `examples/correction-loop/` from that repository.
- **E3. Scope.** The loop with the 2b withdrawals and 2c's governed mode and curation debt, as above.
  Recommended. Not included: deletion of a legacy memory needing `adopt_legacy`, several wikis in one store, and
  `ungated` mode.
- **E4. Retries R1–R4.** As above. R4 needs fcntl, so it is POSIX only, as CI is.
- **E5. CI.** An informational workflow, `.github/workflows/release-b-exit.yml`, runs `run.py` against a wheel
  built from the PR and the newest wiki-studio release in range. It runs on `pull_request` to `main` only when
  the PR changes `src/memkernel/**`, `eval/release-b-exit/**` or the workflow file itself (the owner's path
  filter), weekly by `schedule`, and by `workflow_dispatch`. It is not a required check. A change
  on wiki-studio's side shows up in the weekly run, which installs wiki-studio's newest release. A green
  workflow run is a signal on a wheel built from the PR. The exit evidence is only the recorded run on released
  wheels. The recorded run stays a manual owner step.
- **E6. Closing.** After the recorded run merges, a comment on #48 with the run directory's link and manifest
  hash, ticking the exit evidence. On the owner's go.
- **E7. The upgrade run** (the owner's decision: a separate run with its own directory, not before session 1).
  `run.py --upgrade` records its own attempt, under
  `runs/<date>-upgrade-memkernel-0.6.0-to-<0.7.x>-wiki-studio-<v>/`, in a fresh environment:
  1. **On memkernel 0.6.0 from PyPI:** retain, export through the gate, then the curator marks the pages stable
     and approves them, and a 0.6 import brings them in. This is a store that 0.6.0 itself wrote.
  2. **Upgrade** the same environment to the released 0.7.x wheel, with sha256 checked, and set
     `MEMKERNEL_WIKI_MODE=governed`.
  3. **The first 0.7 import** lists every page under `ambiguous` (`legacy owner unproven`) and writes nothing.
     The check is that no memory is written or changed: the same records, tags and markers before and after. Chroma's files are not compared byte for byte, because SQLite may rewrite them.
  4. **`wiki_import(adopt_legacy=true)`** adopts each page's record, which then carries the wiki's identity. The
     check is that it adopts and does not duplicate.
  5. **One correction through the 0.7 loop:** correct, approve, import, then recall in a new session. The check
     is that the adopted store behaves as a 0.7 store.

  After steps 4 and 5, the upgrade run applies the same convergence checks as the main run: no page key with two
  live memories, no duplicate page or receipt, and no unfinished ledger entry.

  The upgrade run is recorded by the same protocol and under the same rules as the main run.

## Out of scope
Model backends (none on any path), the MCP server processes, human timing (machine time only), Windows, and the
gate checklist items not owned by memkernel.

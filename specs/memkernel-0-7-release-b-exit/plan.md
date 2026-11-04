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

**Retries.** Each is injected in the run script's own process, never by patching the installed packages'
files. Each must converge, which the run checks as follows:
- the same live pages, live memories (by page key and content) and withdrawn or superseded records as a
  fault-free run;
- no page key with two live memories;
- no duplicate page or receipt;
- no unfinished ledger entry.

`ref_id`s and timestamps differ between runs, so the run compares this summary, not a byte hash.
- **R1, an interrupted promote:** a promote interrupted after its commit resolves from its receipt (wiki-studio's
  rule, as in SC-8).
- **R2, an interrupted import:** session 2's import process is killed (`os._exit`, so no `finally` saves the
  ledger) right after its first store write. The run script wraps `MemoryService.retain` in that process, so
  the kill falls exactly after the first write returns, never by timing. Re-running it completes. It relies on memkernel-0-7 FR-004:
  - each import action is idempotent, and the retain deduplicates on this wiki's page key and path;
  - the ledger is rewritten whole at the end of a run, so a killed run leaves the previous ledger, and the next
    run redoes its entries.

  An exception would not test this, because the ledger is saved in a `finally`.
- **R3, everything twice:** export and import each run a second time and change nothing.
- **R4, two imports at once:** two session-2 processes share one store. The first pauses inside its import, on
  a marker file, after its first store write. The second then starts and must not write until the first is
  released, which shows the store's import lock serialized them rather than luck. That lock is
  `exclusive("wiki-import")`, held from the identity checks to the last write, alongside the ledger's file lock.
  memkernel's `tests/integration/test_wiki_scope_processes.py` steers processes the same way. Both must succeed, the second finding everything current, and the convergence checks above
  must pass, the ledger's included.

**Checks.** Each one is named in the output, as wiki-studio's demo does, and the run fails at the first one that
fails.

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
  built from the PR and the newest wiki-studio release in range. It runs on `pull_request` to `main`, weekly by
  `schedule`, and by `workflow_dispatch`, as `wiki-studio-latest.yml` does. It is not a required check. A change
  on wiki-studio's side shows up in the weekly run, which installs wiki-studio's newest release. The recorded run stays a manual owner step.
- **E6. Closing.** After the recorded run merges, a comment on #48 with the run directory's link and manifest
  hash, ticking the exit evidence. On the owner's go.
- **E7. An upgrade step (optional; the owner may drop it).** Before session 1, a session 0 runs memkernel 0.6.0 from PyPI on the same
  store and wiki: retain, export, approve, import. The environment then upgrades to 0.7.0, and session 2 must
  report those pages `ambiguous`, adopt them with `adopt_legacy=true`, and carry on to the same end state. This
  would be the first test on a real 0.6.0 store. It costs one more clean install in the run. Recommended if the
  0.7.0 release notes keep the upgrade step; otherwise the simulated tests above stand.

## Out of scope
Model backends (none on any path), the MCP server processes, human timing (machine time only), Windows, and the
gate checklist items not owned by memkernel.

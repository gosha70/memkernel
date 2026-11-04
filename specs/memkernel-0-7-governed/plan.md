---
spec_mode: full
feature_id: memkernel-0-7-governed
risk_category: feature
justification: "Adds a deployment setting that changes which wiki writer and reader memkernel may use (refusing the unchecked ones), a new section in every session-start block within the fixed 9,000-character budget, an export batch limit, and new frontmatter on exported pages: several modules, a setting, and the contract with wiki-studio, so a full spec."
status: draft
date: 2026-11-03
collaboration_mode: single
origin:
  issue: gosha70/memkernel#48
  urls:
    - https://github.com/gosha70/memkernel/issues/48
    - https://github.com/gosha70/wiki-studio/issues/38
    - https://github.com/gosha70/wiki-studio/blob/main/specs/pitches/38-release-b-governed-curation/pitch.md
  transcripts:
    - specs/memkernel-0-7-governed/origin/2026-11-03-part-2c.md
    - specs/memkernel-0-7-governed/origin/2026-11-03-review-1.md
    - specs/memkernel-0-7-governed/origin/2026-11-03-review-2.md
    - specs/memkernel-0-7-governed/origin/2026-11-03-review-3.md
    - specs/memkernel-0-7-governed/origin/2026-11-03-review-4.md
  origin_claim: |
    Release B part 2c for #48, as wiki-studio's Release B pitch lists memkernel's
    counterpart: "A governed configuration that requires the gate, refuses the
    unchecked fallback writer, and checks info capabilities and the manifest's
    approval_required; an identified ungated mode", and "Curation debt at session
    start (from S6), bounded candidate batches, source content hashes with git
    revision metadata", plus the gate checklist items only the bridge can tick
    (consume receipts, ignore the lock file, honour hash_recipe) and the page_id
    opt-in. The owner (2026-11-03): "Then the Release B 2c spec."
---

# Plan: memkernel 0.7, Release B part 2c: governed mode and curation debt

## What exists (checked 2026-11-03, on main `adabe97`, wiki-studio 0.7.0 installed)
- **Writers and readers.** `WikiExporter` takes the gate when `gate_available()` returns the API, else the
  direct writer (`sync.py:217-247`); `update_index=False` always takes the direct writer. `WikiImporter` reads
  the files directly when wiki-studio is absent and reports `"governed": false` (`sync.py`, `_import_files`). An
  installed but broken or too old wiki-studio (< 0.7.0, `GATE_MIN_VERSION`) is refused, never bypassed
  (`studio.py:209-240`). There is no setting that requires the gate.
- **wiki-studio's contract.** `api.info(paths)` returns `capabilities` (`wiki-lock`, `receipts`,
  `base-revision`, `root-manifest`, `page-id`, `attribution`, `approval-record`, `superseded-by`, `findings` in
  0.7.0, `contract.py:106-116`) and `manifest` with `mode` `governed` (policy `approval_required: true`),
  `managed` (a manifest, default policy) or `legacy` (no manifest), plus `warnings` for schema drift
  (`contract.py:478-530`).
- **Findings.** `api.findings(paths, *, pages=None)` reads only, takes no lock and no model; it returns
  `counts` by kind (all nine kinds, zero included), `pages_checked` and `findings` with `kind`, `severity`,
  `pages`, `description` (`api.py:807-822`, `findings.py:60-120`).
- **Session start.** `MemoryLifecycle.on_session_start` builds the block under `TOTAL_BUDGET = 9_000` with shares
  checkpoint 3,500, context 2,500, candidates 1,200, needs review 1,000; the remaining 800 cover headings,
  health, the wiki pointer and the footer. A comment there reserves part 2c's curation debt a share "from here,
  never add to the total" (`lifecycle.py:69-77`).
- **Export.** Every long-term memory without a page is exported in one run: no batch limit
  (`sync.py:200-212`). A `path:` source is written with no revision (`sync.py:314-318`); wiki-studio's citation
  rules document `path:` with `sha:`, the git commit the page was grounded at
  (`schema/citation-rules.md:13-24`), and lint checks only that `sources:` is present (`lint.py:158-168, 348`).
- **The checklist items.** Receipts are consumed since 0.6 (`ExportReport.proposal`, `submission_digest`,
  `archived_dir`). memkernel reads no ingest log, so `hash_recipe` has no consumer. wiki-studio's lock file is
  `<wiki-parent>/.<wiki-dir>.wiki-studio.lock`. `api.propose(..., assign_page_ids=True)` exists in 0.7.0
  (`api.py:566-615`); memkernel's exports do not pass it.

## Files (for the build)
`src/memkernel/config.py`, `src/memkernel/wiki/sync.py`, `src/memkernel/wiki/studio.py`, `src/memkernel/lifecycle.py`,
`src/memkernel/mcp/tools/wiki.py`, tests, README, CHANGELOG.

## Checked after the first review (2026-11-03)
- `SyncLedger.run()` moves a corrupt ledger aside and saves a fresh one at the end (`ledger.py`, `_load` and
  `_save`); it is a writer, not a reader.
- The direct export calls `lint_wiki` after writing (`sync.py`, end of `export`), which loads wiki-studio when
  installed: today's direct path is not wiki-studio-free.
- The gated export calls `api.init` before `propose` when `index.md` or `log.md` is missing
  (`studio.py`, `propose_and_promote`), and memkernel-0-6 FR-001 keeps no outer rollback: a later rejection can
  leave that scaffold.
- `page-id` is one of wiki-studio 0.7.0's capabilities (`contract.py:106-116`).

## Checked after the second review (2026-11-03)
- `SyncLedger._save` writes a temporary sibling and `os.replace`s it, so an unlocked read sees a whole file.
- In-memory ledgers are process-global dictionaries (`_MEMORY_LEDGERS`, `ledger.py:42`) with no lock;
  `SyncLedger.run()` hands one out by reference.
- `GateUncertainError` (`studio.py`, `propose_and_promote`) is raised when the receipt shows neither a commit nor
  a rollback: some pages may be on disk.
- `api.findings` and `api.info` take no lock (their docstrings, wiki-studio 0.7.0).

## Checked after the third review (2026-11-03)
- `SyncLedger.run()` holds `LOCK_EX` on `<ledger>.json.lock` for the whole import and saves the entries only in its
  `finally` (`ledger.py`, `run` and `_save`): during an import the file on disk is the previous complete ledger.
- `gate_available()` imports wiki-studio and reads its package metadata (`studio.py:209-240`): it can block on a
  slow filesystem, so it belongs inside the bounded child.

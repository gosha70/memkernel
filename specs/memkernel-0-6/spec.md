# Spec: memkernel 0.6 — the Release B wiki bridge

Origin: memkernel #48 and its owner decisions (comments of 2026-10-24 and 2026-10-25), wiki-studio #38 and its Release B pitch.
Part 1 (US1–US2) is buildable against wiki-studio 0.6.0; part 2 (US3+) waits for wiki-studio 0.7.0.

## User Scenarios
- **US1 (part 1):** A memkernel agent exports long-term memories to a wiki that another wiki-studio writer is
  changing at the same time. Both writes land; neither is reverted; a failed export leaves wiki-studio's own
  rollback and receipt as the only recovery, and the export reports the failure.
- **US2 (part 1):** A maintainer can tell, from what memkernel records about an export, which wiki-studio
  proposal it was, so a replayed export is recognised and does not duplicate anything.
- **US3+ (part 2, needs wiki-studio 0.7.0):** import only approved revisions; corrections supersede the memories
  they correct; withdrawal on supersession, deprecation and deletion; governed configuration. Not specified yet.

## Requirements
- **FR-001 (no outer snapshot):** `WikiExporter`'s gated path MUST NOT snapshot or restore wiki files. On
  `GateError` or `OSError` from the gate it reports `gate_error` with the exception's message, counts the pages
  as skipped, and writes nothing itself. `_WikiSnapshot` is removed. A failure after FR-002's `api.init` (for
  example in `propose`) leaves the new `index.md` and `log.md` in place: a valid, empty scaffold, not removed.
  memkernel 0.5 left a fresh wiki with no files after a rejected export; the CHANGELOG says so, and the
  `gate_error` field's comment ("nothing was written") is corrected to "no page was written". The one exception,
  where wiki-studio fails after it has committed the pages, is FR-009.
- **FR-002 (scaffold through wiki-studio):** before proposing, the gated path MUST create a missing `index.md`
  and `log.md` with `api.init` (never overwrites; exclusive create), not with memkernel's own scaffold. The direct
  writer (no wiki-studio) keeps memkernel's scaffold. memkernel-0-5 SC-2's byte-identity therefore covers pages
  and appended index and log lines, not the scaffold of a new wiki; an existing wiki is unaffected. The difference
  is visible: wiki-studio 0.6.0's scaffold has `status: stable` and titles `Wiki` / `Wiki log`, memkernel's has
  `status: draft` and `Wiki Index` / `Wiki Edit Log`. The CHANGELOG says so, so a new wiki's `index.md` is not
  read as a bug.
- **FR-003 (version floor):** the `wiki` extra MUST require `wiki-studio >=0.6.0,<1`; `gate_available()` MUST
  raise `GateError` (never fall back to unchecked writes) when an installed wiki-studio is older than 0.6.0 or
  lacks `api.init`. ADR-010 gains an addendum recording the floor and why (scoped commit, exception rollback,
  receipts and the advisory lock arrived in 0.6.0).
- **FR-004 (dev lock):** `poetry.lock` pins wiki-studio 0.6.0 for development and CI; moving it to 0.7.0 when
  published is a lock-only change.
- **FR-005 (receipt reference):** a successful gated export MUST report, in new optional `ExportReport` fields
  defaulting to `None` (always `None` for the direct writer):
  - `proposal`: the proposal name memkernel passed to `api.propose`;
  - `submission_digest`: as the receipt records it;
  - `archived_dir`: `PromoteResult.archived_dir`, or `None` when wiki-studio committed the edits but its archive
    step failed (0.6.0 treats step 4 as housekeeping: `_archive_and_cleanup` catches `OSError` and returns
    `None`). memkernel then reports the export as promoted, not archived, and does not finish the archive itself;
    promoting the proposal directory again finishes it and applies nothing twice;
  - `archive_hint`: set only in that case, and also logged as a warning. It says how to clear the state: the
    promote command, with the actual proposal directory and the `--root`, `--wiki-dir` and `--proposals-dir`
    memkernel used, all absolute (as wiki-studio's `WikiPaths` holds them), so it works from any directory, finishes the archive and applies nothing twice. The command runs through the interpreter
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
  and `archived_dir` for a gated export, `archive_hint` when `archived_dir` is null, and `receipt_error` when the
  receipt was unreadable; keys absent otherwise, as `gate_error` is today. The tool's description is updated (it
  still says "wiki-studio >= 0.3" and that a rejected export "writes nothing"), and the CHANGELOG lists each
  added response key, as 0.5 did for `lint`, `lint_hint`, `lint_error` and `gate_error`. The tool count is
  unchanged.

- **FR-009 (committed, then failed):** wiki-studio can commit the pages and then raise, for example when it
  cannot rewrite its receipt as committed ("the edits were committed to the wiki … Promote the directory again to
  finish"). When the gate raises after `propose` returned a proposal directory, memkernel MUST check whether the
  commit happened, using wiki-studio's own record: the receipt left in that directory (state `committing` or
  `committed`) and, for every page memkernel created, that the page's on-disk sha256 equals the receipt's
  `post_sha256` for that path. wiki-studio writes that receipt before any wiki write, so a missing receipt means
  nothing was committed (a refusal such as a create of an existing page) and is a `gate_error`, even when a page
  with identical bytes is on disk. Only if the receipt exists but cannot be read or has no usable
  `planned_writes`, it falls back to comparing each page's bytes on disk with the content memkernel proposed. If the check holds, the export is
  reported as written and gated: the pages in `written`, `proposal`, `submission_digest` from the receipt when
  readable, `archived_dir` null, no `gate_error`, and `archive_hint` with the promote command (FR-005) that
  finishes it, preceded by wiki-studio's message; the hint is also logged as a warning. If the check does not
  hold (validation refused, or wiki-studio rolled back), it is a `gate_error` as in FR-001. memkernel never runs
  the promote again itself: that is the user's step, as the hint says.

## Constraints / What NOT to Build
- No held-lock route (owner decision 1: snapshot removal chosen). No change to wiki-studio.
- Nothing of part 2 (review state, `corrects`, withdrawal, governed mode) in part 1.
- No merge to `main` before the `v0.5.0` tag; `core/` unchanged; no new runtime dependency (wiki-studio stays
  an optional extra).

## Key Entities
- `ExportReport` (existing): gains `proposal`, `submission_digest`, `archived_dir`, `archive_hint` and `receipt_error` (optional).
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
- SC-7: With wiki-studio forced to fail after its commit (the receipt rewrite as committed), the export reports
  the page as written and gated, `archived_dir = None`, no `gate_error`, and an `archive_hint` whose command,
  run as given, finishes the promotion without changing the page. With the receipt present but unreadable, the
  content check reports the page as written. A refusal before any receipt (another export created the same page
  with identical bytes), a receipt whose state records no commit, and a rolled-back failure report `gate_error`.

## Disclosures and deviations

Everything above this heading is the unchanged output of `report.py` for the committed receipts. This section is
written by the maintainer and reviewed; it is not generated. Each statement says where its evidence is:
**[receipts]** the committed `receipts.jsonl`; **[run record]** a file of the run kept outside git, with its
sha256 where given; **[operator]** the operator's terminal output or Claude Console screenshots, attested by the
maintainer, not independently recorded.

### 1. How this report is reproduced (procedural deviation from SC-8)

SC-8 of `specs/memkernel-0-5/spec.md` asks that the report step reproduce this file byte for byte "from the
receipts". The frozen `report.py` has no input for written disclosures, and the preregistration requires them
in the report. This file is therefore assembled from three committed inputs, not from the receipts alone: the
receipts, the report parameters (`report-params.json`: title, SHAs, tag, the calibration's live-compaction
finding) and this reviewed section. The generated part is not edited. From `eval/lifecycle-suite/`:

```bash
set -euo pipefail
run=results/measured-20261027T002737Z
python3 report.py --receipts "$run/receipts.jsonl" \
  --receipts calibration/receipts-20261024T033046Z.jsonl \
  --params "$run/report-params.json" --preregistration preregistration.md > /tmp/generated.md \
  && { cat /tmp/generated.md; printf '\n'; cat "$run/disclosures.md"; } | cmp - report-0.5.0.md
```

A failure of `report.py` stops the command before the comparison.

### 2. What is committed

The preregistration says "Only `receipts.jsonl` is committed". Its intent, keeping raw streams, stores and
workspaces out of git, holds: the run's 19,419 files stay on the operator's machine **[operator]**. This release
also commits `report-params.json` and this `disclosures.md`, as reproduction metadata. That is recorded here as
a clarification of the rule, not treated as silently compliant. The committed receipts were scanned with
`scan_secrets.py`: 0 hits. The scan of the whole run directory found 0 credential patterns; it refused 519
binary or non-UTF-8 files (Chroma stores, `.pyc` and agent workspace files), none of which is committed.

### 3. The memkernel arm's compaction hooks (known defect, scored as frozen)

The memkernel arm runs the hook scripts in `templates/hooks/` at the freeze SHA. While the run was in progress
(2026-10-27), a review found defects in them; the owner chose to complete the run as frozen and disclose them
here. No result was rescored.

- `PreCompact` receives no summary from Claude Code, so the hook stores a placeholder checkpoint. Being the
  newest checkpoint, it hides the agent's own checkpoint from the next `SessionStart` (reproduced outside the
  run).
- `PostCompact`'s output is not injected into the session by Claude Code, and the hook discards the
  `compact_summary` it is given. Recovery after compaction comes only from `SessionStart` with source `compact`.
- `SessionStart` ignores its source: in `lc-compact` it ran 125 times over 25 sessions, five per session
  **[receipts]**, each time injecting the same block.

Observed outcome **[receipts]**: in `lc-compact` all 25 memkernel trials were valid; `PreCompact` and
`PostCompact` each ran once per trial with exit status 0; memkernel passed 25 of 25, and so did every other arm,
`bare` included. This is an observed outcome, not evidence that the defects had no effect: with every arm at
25 of 25, `lc-compact` hit a ceiling in this run and cannot separate the arms in either direction. That ceiling
is the reason no conclusion about memkernel's compaction hooks can be drawn from this run; the `lc-compact` table
is not support for the hooks, nor evidence against them.

### 4. Four failed `SessionStart` hook runs (scored as frozen)

Four of the memkernel arm's `SessionStart` hook runs exited with status 1 **[receipts]**: the first session of
`lc-wiki-backoff` runs 0 and 3 and of `lc-retain-rounding` run 4, and the first of five `SessionStart` runs in
`lc-compact-page-size` run 4. In each, the hook failed with `chromadb.errors.InternalError: ... table
collections already exists` **[run record]**: in a chain's first session the hook and memkernel's MCP server
opened the new, empty store at the same moment and both tried to create its tables. Three were in the first,
ungraded session of a two-session chain, whose store was empty, so the hook had nothing to inject; in the
fourth, the later `SessionStart` runs of the same session succeeded. All four trials are valid and were scored
on their checker outcome, as the frozen rules require: FR-015a keeps every trial with a failed hook valid, and
turns a failed or missing `PreCompact` or `PostCompact` hook into an unsuccessful outcome; a failed
`SessionStart` hook is not one of those, so it does not change the outcome. (`report.py`'s docstring says
"failed hooks" more broadly than this rule.) The race is a memkernel defect, reported here and to be fixed
after this release.

### 5. The code freeze and the tag (deviation)

FR-017 requires `eval/check_freeze.py 641a508a2289b2d20775e6d149a0bb47678d1621` to pass between the freeze and
the `v0.5.0` tag. Before the tag, `main` received two changes outside its allowlist: the memkernel 0.6
specification (#53) and the `wiki_studio` arm's own wiki-studio pin (#56); on `main` the check then reported 16
violations. Neither touches the measured code, the image or the arm configuration: the image was built from
the freeze SHA before they merged. `v0.5.0` is therefore tagged on `release/0.5`, branched from the
preregistration merge `8674480350ad9e95888e2e53fe7809ae36dbc38e` and carrying only allowlisted files, where the
check passes (its output is in the release pull request); `release/0.5` is then merged into `main`.

### 6. The wiki-bridge wiring check (task 18a)

As preregistered, the check ran before `measure` on the measured image, and again after the run
**[operator]**; both passed all 14 steps. Image `memkernel-calibration:641a508a2289`, ID
`sha256:73900a618dead9f73686962d6ed942ad6d73da5b027667c9b80559efa42f6425`, code `641a508`, check
`wiring_check.py` sha256 `84ee944463ec52fe19aa65a644cc4136b0043ef2b71b966653d7aae699f4a3f0`, run from a clean
`git archive` of the freeze commit. The first run's output carries no timestamp; it was printed after
`vm.sh check` and `vm.sh demo` and before `measure` in the operator's terminal.

### 7. Run identity, isolation, spend and credentials

- **Code and environment [receipts, run record]:** code `641a508a2289b2d20775e6d149a0bb47678d1621` and model
  `claude-sonnet-5-5` in every receipt; preregistration commit `ddbe218441414243b97746109640fbf6caed82fa`, its
  file's sha256 `aa20a2173a24955121f62004cc45b06eb25233e2dcac8547474b0626149040c9` named by every receipt.
  `environment.txt` (sha256 `5d6d8a783e55d2bc…`): Claude Code 2.1.288, wiki-studio 0.4.1 for the
  `wiki_studio` arm, embedding model `sentence-transformers/all-MiniLM-L6-v2` at revision
  `1110a243fdf4706b3f48f1d95db1a4f5529b4d41`, `run.sh` sha256 `4651d6d4b950ae1c…`.
- **Announcement [run record]:** the preregistration was announced on gosha70/memkernel#17
  (issuecomment-6430336336) at 2026-10-27T00:07:19Z, not edited; the run's ID records its start,
  2026-10-27T00:27:37Z.
- **Isolation [operator]:** before the run, `vm.sh check` on the throwaway Lima VM reported no shared folders,
  no access to the Mac's home directory, no credential files, no SSH agent, only Lima's own login key, no
  secret-named environment variables, the host block rejecting 20 of 20 probes from the VM and 9 of 9 from a
  container of the measured image, and the API answering 401 without a key.
- **Spend [operator]:** a dedicated Claude Console workspace, `memkernel-measured`
  (`wrkspc_01DjRechyLWV2YpA25K9YLHa`), with a $150 monthly limit as preregistered; Console cost $63.85 (data
  as of 2026-10-27 10:36 UTC), against the preregistered estimate of $80.74 ($104.96 with the 30 percent
  margin). Console tokens: 127,940,963 in, 1,801,886 out, all Claude Sonnet 5.5. The receipts' input,
  cache-write and cache-read tokens plus the compaction estimate come to 127,672,231 **[receipts]**, 0.21
  percent below the Console; the output differs by 251,200 tokens, the compaction summaries, which the
  receipts do not record.
- **Credentials and cleanup [operator]:** the API key existed only for this workspace and was passed at run
  time, never stored in the image. After the runs were copied and verified (19,419 files, sha256 per file), the
  key was deleted, the workspace archived and the VM destroyed, on 2026-10-27.

### 8. Reading the primary result

Against `claude_md` the interval, +4.0 to +29.0 points, lies above zero, but the label is "no detectable
difference", and no gain is claimed. That is the preregistered rule, not an oversight: the label comes from the
exact sign test after Holm, and the bootstrap interval is approximate at this number of tasks and does not
override it. The test did not reject: memkernel was ahead on 6 tasks, behind on none, and tied on 14
**[receipts]**, so the raw two-sided p is 0.03125 and the Holm-adjusted p 0.0625. With only 6 non-tied tasks the
design could not have reached significance: even a 6–0 split has a smallest attainable adjusted p of 0.0625; at
least 7 non-tied tasks are needed. Ten of the 14 ties are the `lc-wiki` and `lc-compact` tasks, where every arm
passed every trial; the remaining four are in `lc-retain` and `lc-reval`, the only groups that separated the
arms (memkernel ahead on 3 tasks in each). Against `fs_grep`, memkernel was ahead on 1 task and tied on 19, and
the whole interval, +0.0 to +9.0, lies within the preregistered +/-10 point band, so the label is "equivalent".
What this run can show is therefore limited mainly by its ceilings, which is a property of the task set as
frozen, not of either arm.

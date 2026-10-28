# memkernel 0.5 lifecycle evaluation

**Maintainer-run supplemental evaluation.** These numbers come from memkernel's own lifecycle runner (`eval/lifecycle-suite/`), not from a third-party harness. Failures, nulls and invalid trials are reported.

**What each arm keeps between sessions.** `memkernel` keeps only its memory store: its workspace is reset to the task fixture every session, unlike a real project where files persist too. `claude_md` keeps only its files, `fs_grep` only earlier transcripts, and `bare`, `placebo` and `protocol` nothing. The primary comparison is therefore the memory store alone against files alone, not memkernel against a typical project setup. `wiki_studio` (wiki-studio's command-line tool, told never to run its model-backed verbs; the diagnostics count any call that did) keeps nothing beyond the lc-wiki shared wiki and runs on lc-wiki only; it is compared with the same file-based arms in its own table, never with memkernel.

- Code-freeze SHA: `641a508a2289b2d20775e6d149a0bb47678d1621`
- Preregistration commit: `ddbe218441414243b97746109640fbf6caed82fa`
- Release tag: `v0.5.0`
- Model: `claude-sonnet-5-5`
- Measured sessions: 1160; trials: 625


## Primary endpoint (all tasks pooled)

The task is the unit: per task, memkernel's success rate minus the comparator's over its valid pairs. Exact two-sided sign test over the non-tied tasks (tied tasks are left out and counted), Holm over the 2 primary comparators at alpha 0.05; mean effect in percentage points, each task weighted equally, with a 95% percentile bootstrap interval over tasks (10000 resamples, seed 17; approximate at this number of tasks). Equivalent means the whole interval lies within +/-10 points.

| memkernel vs | Tasks | Valid pairs | memkernel ahead | Comparator ahead | Tied | Sign test p | Holm-adjusted p | Mean effect (points) | Interval (points) | Label |
|---|---|---|---|---|---|---|---|---|---|---|
| claude_md | 20 | 100 | 6 | 0 | 14 | 0.0312 | 0.0625 | +15.0 | +4.0 to +29.0 | no detectable difference |
| fs_grep | 20 | 100 | 1 | 0 | 19 | 1.0000 | 1.0000 | +3.0 | +0.0 to +9.0 | equivalent |

**Headline:** no gain claimed (a gain needs every primary comparator labelled gain). Requiring every comparator to pass after Holm is deliberately stricter than an intersection-union test.

Per-group tables below are descriptive: a group of five tasks cannot reach p < 0.05 with a sign test.

## lc-retain

| Arm | Trials | Valid | Passed | Failed | Timeout | No answer | Invalid (reason: count) | Truncated |
|---|---|---|---|---|---|---|---|---|
| bare | 25 | 25 | 2/25 (8%) | 23 | 0 | 0 | none | 0 |
| placebo | 25 | 25 | 5/25 (20%) | 20 | 0 | 0 | none | 0 |
| protocol | 25 | 25 | 2/25 (8%) | 23 | 0 | 0 | none | 0 |
| claude_md | 25 | 25 | 15/25 (60%) | 10 | 0 | 0 | none | 0 |
| fs_grep | 25 | 25 | 25/25 (100%) | 0 | 0 | 0 | none | 0 |
| memkernel | 25 | 25 | 25/25 (100%) | 0 | 0 | 0 | none | 0 |
| wiki_studio | 0 | 0 | 0/0 | 0 | 0 | 0 | none | 0 |

| memkernel vs | Valid pairs | Both pass | memkernel only | Comparator only | Neither | Pairs removed | Pairs truncated | Mean effect (points, descriptive) |
|---|---|---|---|---|---|---|---|---|
| claude_md (primary) | 25 | 15 | 10 | 0 | 0 | 0 | 0 | +40.0 |
| fs_grep (primary) | 25 | 25 | 0 | 0 | 0 | 0 | 0 | +0.0 |
| bare (secondary) | 25 | 2 | 23 | 0 | 0 | 0 | 0 | +92.0 |
| placebo (secondary) | 25 | 5 | 20 | 0 | 0 | 0 | 0 | +80.0 |
| protocol (secondary) | 25 | 2 | 23 | 0 | 0 | 0 | 0 | +92.0 |

| Arm | Bash calls running `wiki-studio ingest`/`query` (of all Bash calls) | Write/Edit calls under the wiki (of all Write/Edit calls) |
|---|---|---|
| bare | 0/37 | 0/117 |
| placebo | 0/25 | 0/124 |
| protocol | 0/36 | 0/114 |
| claude_md | 0/17 | 0/114 |
| fs_grep | 0/13 | 0/124 |
| memkernel | 0/10 | 0/57 |

## lc-reval

| Arm | Trials | Valid | Passed | Failed | Timeout | No answer | Invalid (reason: count) | Truncated |
|---|---|---|---|---|---|---|---|---|
| bare | 25 | 25 | 5/25 (20%) | 20 | 0 | 0 | none | 0 |
| placebo | 25 | 25 | 5/25 (20%) | 20 | 0 | 0 | none | 0 |
| protocol | 25 | 25 | 5/25 (20%) | 20 | 0 | 0 | none | 0 |
| claude_md | 25 | 25 | 20/25 (80%) | 5 | 0 | 0 | none | 0 |
| fs_grep | 25 | 25 | 22/25 (88%) | 3 | 0 | 0 | none | 0 |
| memkernel | 25 | 25 | 25/25 (100%) | 0 | 0 | 0 | none | 0 |
| wiki_studio | 0 | 0 | 0/0 | 0 | 0 | 0 | none | 0 |

| memkernel vs | Valid pairs | Both pass | memkernel only | Comparator only | Neither | Pairs removed | Pairs truncated | Mean effect (points, descriptive) |
|---|---|---|---|---|---|---|---|---|
| claude_md (primary) | 25 | 20 | 5 | 0 | 0 | 0 | 0 | +20.0 |
| fs_grep (primary) | 25 | 22 | 3 | 0 | 0 | 0 | 0 | +12.0 |
| bare (secondary) | 25 | 5 | 20 | 0 | 0 | 0 | 0 | +80.0 |
| placebo (secondary) | 25 | 5 | 20 | 0 | 0 | 0 | 0 | +80.0 |
| protocol (secondary) | 25 | 5 | 20 | 0 | 0 | 0 | 0 | +80.0 |

| Arm | Bash calls running `wiki-studio ingest`/`query` (of all Bash calls) | Write/Edit calls under the wiki (of all Write/Edit calls) |
|---|---|---|
| bare | 0/16 | 0/92 |
| placebo | 0/16 | 0/97 |
| protocol | 0/14 | 0/89 |
| claude_md | 0/16 | 0/83 |
| fs_grep | 0/8 | 0/100 |
| memkernel | 0/15 | 0/49 |

## lc-wiki

| Arm | Trials | Valid | Passed | Failed | Timeout | No answer | Invalid (reason: count) | Truncated |
|---|---|---|---|---|---|---|---|---|
| bare | 25 | 25 | 25/25 (100%) | 0 | 0 | 0 | none | 0 |
| placebo | 25 | 25 | 25/25 (100%) | 0 | 0 | 0 | none | 0 |
| protocol | 25 | 25 | 25/25 (100%) | 0 | 0 | 0 | none | 0 |
| claude_md | 25 | 25 | 25/25 (100%) | 0 | 0 | 0 | none | 0 |
| fs_grep | 25 | 25 | 25/25 (100%) | 0 | 0 | 0 | none | 0 |
| memkernel | 25 | 25 | 25/25 (100%) | 0 | 0 | 0 | none | 0 |
| wiki_studio | 25 | 25 | 25/25 (100%) | 0 | 0 | 0 | none | 0 |

| memkernel vs | Valid pairs | Both pass | memkernel only | Comparator only | Neither | Pairs removed | Pairs truncated | Mean effect (points, descriptive) |
|---|---|---|---|---|---|---|---|---|
| claude_md (primary) | 25 | 25 | 0 | 0 | 0 | 0 | 0 | +0.0 |
| fs_grep (primary) | 25 | 25 | 0 | 0 | 0 | 0 | 0 | +0.0 |
| bare (secondary) | 25 | 25 | 0 | 0 | 0 | 0 | 0 | +0.0 |
| placebo (secondary) | 25 | 25 | 0 | 0 | 0 | 0 | 0 | +0.0 |
| protocol (secondary) | 25 | 25 | 0 | 0 | 0 | 0 | 0 | +0.0 |

| wiki_studio vs | Valid pairs | Both pass | wiki_studio only | Comparator only | Neither | Pairs removed | Pairs truncated | Mean effect (points, descriptive) |
|---|---|---|---|---|---|---|---|---|
| claude_md (primary) | 25 | 25 | 0 | 0 | 0 | 0 | 0 | +0.0 |
| fs_grep (primary) | 25 | 25 | 0 | 0 | 0 | 0 | 0 | +0.0 |

| Arm | Bash calls running `wiki-studio ingest`/`query` (of all Bash calls) | Write/Edit calls under the wiki (of all Write/Edit calls) |
|---|---|---|
| bare | 0/113 | 6/19 |
| placebo | 0/79 | 25/50 |
| protocol | 0/98 | 10/32 |
| claude_md | 0/104 | 6/27 |
| fs_grep | 0/7 | 52/78 |
| memkernel | 0/40 | 38/63 |
| wiki_studio | 0/177 | 0/9 |

## lc-compact

| Arm | Trials | Valid | Passed | Failed | Timeout | No answer | Invalid (reason: count) | Truncated |
|---|---|---|---|---|---|---|---|---|
| bare | 25 | 25 | 25/25 (100%) | 0 | 0 | 0 | none | 0 |
| placebo | 25 | 25 | 25/25 (100%) | 0 | 0 | 0 | none | 0 |
| protocol | 25 | 25 | 25/25 (100%) | 0 | 0 | 0 | none | 0 |
| claude_md | 25 | 25 | 25/25 (100%) | 0 | 0 | 0 | none | 0 |
| fs_grep | 25 | 25 | 25/25 (100%) | 0 | 0 | 0 | none | 0 |
| memkernel | 25 | 25 | 25/25 (100%) | 0 | 0 | 0 | none | 0 |
| wiki_studio | 0 | 0 | 0/0 | 0 | 0 | 0 | none | 0 |

| memkernel vs | Valid pairs | Both pass | memkernel only | Comparator only | Neither | Pairs removed | Pairs truncated | Mean effect (points, descriptive) |
|---|---|---|---|---|---|---|---|---|
| claude_md (primary) | 25 | 25 | 0 | 0 | 0 | 0 | 0 | +0.0 |
| fs_grep (primary) | 25 | 25 | 0 | 0 | 0 | 0 | 0 | +0.0 |
| bare (secondary) | 25 | 25 | 0 | 0 | 0 | 0 | 0 | +0.0 |
| placebo (secondary) | 25 | 25 | 0 | 0 | 0 | 0 | 0 | +0.0 |
| protocol (secondary) | 25 | 25 | 0 | 0 | 0 | 0 | 0 | +0.0 |

| Arm | Bash calls running `wiki-studio ingest`/`query` (of all Bash calls) | Write/Edit calls under the wiki (of all Write/Edit calls) |
|---|---|---|
| bare | 0/13 | 0/95 |
| placebo | 0/24 | 0/95 |
| protocol | 0/15 | 0/95 |
| claude_md | 0/12 | 0/95 |
| fs_grep | 0/12 | 0/95 |
| memkernel | 0/14 | 0/59 |

## Token usage (measured)

- Tokens: input 12092, cache write 13420803, cache read 108759629, output 1550686
- Compaction calls, estimated input (sum of compact_boundary.pre_tokens; not in the tokens above; the summaries' output is not recorded): 5479707
- `lc-compact` sessions with exactly one compaction: 150 of 150

| Arm | Receipts: input + cache write + cache read | Compaction estimate (input only) | Receipts plus estimate |
|---|---|---|---|
| bare | 19024792 | 900097 | 19924889 |
| claude_md | 18613900 | 902908 | 19516808 |
| fs_grep | 20402363 | 907622 | 21309985 |
| memkernel | 19661512 | 930495 | 20592007 |
| placebo | 20069784 | 917227 | 20987011 |
| protocol | 20110428 | 921358 | 21031786 |
| wiki_studio | 4309745 | 0 | 4309745 |

## API errors (measured)

Counts are error events, not failed calls: one refused call appears both as an assistant message and as a result, under two keys.

- None.

- Truncation: none.

## Label

Inferential: every primary comparison has at least 80 valid pairs covering at least 16 tasks.

## Calibration (not scored)

- Sessions: 50
- Tokens: input 570, cache write 760404, cache read 5583011, output 73080
- Compaction calls, estimated input (sum of compact_boundary.pre_tokens; not in the tokens above; the summaries' output is not recorded): 440632
- `lc-compact` sessions with exactly one compaction: 12 of 12
- API error events: unknown for 50 session(s) (schema version 2 receipts do not record them)
- Invalid sessions: none
- Live compaction proven: yes: all 12 calibration lc-compact sessions recorded exactly one compaction between exposure and evaluation (calibration/RECORD-2026-10-24.md)
- Calibration sessions are not graded; no pass/fail exists for them.

| Arm | Sessions | input min / median / max | cache_write min / median / max | cache_read min / median / max | output min / median / max |
|---|---|---|---|---|---|
| bare | 8 | 6 / 8 / 22 | 5778 / 6482 / 40711 | 47645 / 66122 / 245508 | 646 / 1118.5 / 2693 |
| claude_md | 8 | 6 / 8 / 22 | 5936 / 6538.5 / 41172 | 47598 / 66382 / 246629 | 745 / 1129 / 2885 |
| fs_grep | 8 | 6 / 8 / 22 | 6556 / 7510 / 41287 | 47982 / 68826.5 / 247789 | 859 / 1146.5 / 2985 |
| memkernel | 8 | 6 / 8 / 24 | 6635 / 7579 / 43735 | 49567 / 68696.5 / 281122 | 626 / 1025 / 2977 |
| placebo | 8 | 6 / 8 / 22 | 6262 / 6993 / 41480 | 48705 / 67889 / 251417 | 782 / 1320 / 3022 |
| protocol | 8 | 8 / 9 / 22 | 6463 / 7417 / 41823 | 67305 / 77671 / 253729 | 668 / 1270 / 2866 |
| wiki_studio | 2 | 8 / 9 / 10 | 7241 / 7558 / 7875 | 68658 / 78083.5 / 87509 | 711 / 1175 / 1639 |

| Arm | Receipts: input + cache write + cache read | Compaction estimate (input only) | Receipts plus estimate |
|---|---|---|---|
| bare | 985747 | 72172 | 1057919 |
| claude_md | 1007620 | 72695 | 1080315 |
| fs_grep | 1028042 | 72975 | 1101017 |
| memkernel | 1022591 | 75151 | 1097742 |
| placebo | 1030495 | 73566 | 1104061 |
| protocol | 1098189 | 74073 | 1172262 |
| wiki_studio | 171301 | 0 | 171301 |

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
  percent below the Console; the output is 251,200 tokens short, most likely the compaction summaries, which
  the receipts do not record (not measured). The workspace ID is given in full, as in the calibration record.
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

### 9. The preregistration's session count (deviation)

The preregistration says "625 chains and 1,100 sessions: 2 sessions per chain in `lc-retain`, `lc-reval` and
`lc-wiki`, 1 in `lc-compact`". The chain count is right; the session count is not: two frozen `lc-retain` tasks,
`lc-retain-retry-revised` and `lc-retain-separator-revised`, are three-session chains (the revised-fact variant),
so the run had 415 two-session, 150 one-session and 60 three-session chains, 1,160 sessions **[receipts]**. The
tasks were run as frozen; the chains, the trials and the analysis are unaffected. The cost estimate was
computed per chain from the calibration, whose only `lc-retain` task was a two-session chain, so it understated
these 60 sessions by about $2.07 before its 20 percent allowance (60 sessions at the `lc-retain` estimate of
$10.33 for 150 two-session chains); the run cost $63.85 against the estimate of $80.74 and the $150 limit.

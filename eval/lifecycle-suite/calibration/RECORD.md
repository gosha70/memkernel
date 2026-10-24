# Calibration record: `calibration-20261018T215648Z` (task 18)

The calibration run that `specs/memkernel-0-5` FR-015 requires before the
freeze. Nothing here is graded, and none of it enters the measured results.
Every receipt figure below comes from the run's `receipts.jsonl`. The cost and
the Console token counts come from the Claude Console.

**Status:** the run is accepted as evidence that the runner works and that live
compaction happens. It is **superseded**: the owner chose to fix the Hugging
Face network access (option A in [Open items](#open-items), decided
2026-10-20 UTC), which changes the runtime, so a new calibration on a new image
follows before the freeze. Task 18a stays unticked until it is re-run on that
image; its pass below applies to image `sha256:ba4dc322…` only.
The calibration that replaces it is `calibration-20261024T033046Z`, recorded
in `RECORD-2026-10-24.md`.

**Token figures.** The receipts miss the `/compact` steps (see below). Spend
and any budget for the measured run are based on the Console's totals and the
$3.53, not on the receipts. Every receipt figure in this record excludes the
`/compact` steps.

## Configuration

| | |
|---|---|
| Run | `calibration-20261018T215648Z`, 2026-10-18 21:56:49Z to 22:13:47Z (17 min) |
| Model | `claude-sonnet-5-5` (approved 2026-10-17, cap $30) |
| Code | `12a3ff3b60e3c6daf62a11fe152a5e2d09f0c387` (clean, the merge of #34) |
| Image | `memkernel-calibration:12a3ff3b60e3`, ID `sha256:ba4dc322d182d1095de0c948ebe0022f5e1a8419fa3d2744e33c855eb059eaa6` |
| Tools in the image | Claude Code 2.1.288, wiki-studio 0.4.1 |
| `run.sh` sha256 | `f703d8e656e41db9b0f3aff8cb437b2f1d0c9d1ad845829483c38af606119d5b` |
| Environment (`/opt/environment.txt`) sha256 | `c7e6fdb92ccd8480d873191f8b287dc7aff2cf5f2d81af40653bbf1a8e5a5345` |
| Tasks | the five in `tasks.txt`: `lc-retain-rounding`, `lc-reval-timeout-units`, `lc-wiki-backoff`, `lc-compact-port`, `lc-compact-name-order` |
| Arms | `bare`, `claude_md`, `fs_grep`, `memkernel`, `placebo`, `protocol` on every task; `wiki_studio` on `lc-wiki-backoff` only |
| `receipts.jsonl` sha256 | `d05c3e51a5a4fd3488db3b7fe08a672a887d6ab604a0a3dbef6a0b87fc9bc063` |

**Compaction setting.** An `lc-compact` task has a `{"compact": true}` step
between its exposure and evaluation stages, and the runner sends `/compact` at
that step. The streams record each compaction with `trigger: manual`. No
context-size setting is involved. This setting is part of the tasks and is
frozen with them.

**The image can't be rebuilt.** Rebuilding the same commit gave three other
image IDs (`f97e82e2…`, `729c6dd5…`, `787225fc…`). The calibrated image is
kept as `memkernel-calibration-image-ba4dc322d182.tar.gz`, with archive sha256
`2df330fb624162bb4971bb8dcdf449c80ed8bd55776f31590bd1b5b7ed4acbbe`, and
`vm.sh load-image` restores it.

## Isolation and spend (FR-015, FR-018)

- **Where it ran:** a throwaway local Lima VM, `mk-calibration`: 4 CPUs, 8 GB,
  40 GB disk, created with `--mount-none`, no SSH agent or X11 forwarding, and
  rootless Docker inside. The calibration container ran in it.
- **No personal credentials:** `vm.sh check` showed no shared folders, no
  `/Users/…` path, no credential files, no SSH agent, no environment variables
  that look like secrets, and only Lima's own login key in `authorized_keys`.
  This is not full isolation: the VM could reach services listening on the
  Mac (open item 3).
- **Workspace:** the dedicated Console workspace `memkernel-calibration`
  (`wrkspc_0…`). Its monthly spend limit of $30.00 was verified in the Console
  before the first session, with $0.00 spent at that point. `preflight` matched
  the key's `anthropic-workspace-id` to that workspace.
- **Key:** a new key, scoped to that workspace only, with a 7-day expiry. It
  was given to the VM at a hidden prompt and never written to a file.
- **Afterwards:** the key was deleted and the workspace archived on 2026-10-18
  local time (2026-10-19 UTC). The VM was deleted on 2026-10-20 UTC, after the
  runs were fetched and verified (52 files, sha256 each) and the image was
  saved.
- **Secret scan:** `scan_secrets.py` reported 0 hits over the run directory.
- **Raw data:** neither this run's receipts nor its raw streams are committed,
  because the new calibration supersedes this one; the receipts' sha256 above
  identifies them. For the new calibration, only `receipts.jsonl` is
  committed, after the owner has reviewed it. Raw streams stay outside any git
  checkout (FR-018).

## Cost

**$3.53**, as shown in the Console for the workspace, against the $30 limit.

## Results

- **Sessions:** 50 receipts, all `phase: calibration` and all valid. Every
  `outcome` and `checker_passed` is null, so nothing was graded.
- **Exclusions:** none.
- **Steps:** all 86 steps ended `success`, and none was flagged as an error.
- **Live compaction:** proven. All 12 `lc-compact` sessions (2 tasks × 6 arms)
  recorded exactly one compaction, and each lies between its exposure and
  evaluation timestamps. `lc-compact` stays in the measured run.
- **Hooks (memkernel arm only):**
  - The arm has 8 sessions and 20 hook runs, all exit 0
    (`hooks_succeeded` 20/20).
  - Each of its 2 compaction sessions ran 7 hooks, in this order:
    `SessionStart` ×3, `PreCompact`, `SessionStart`, `PostCompact`,
    `SessionStart`. That is 14 runs in total, 2 of them `PreCompact` and 2
    `PostCompact`.
  - Each of the other 6 sessions ran one `SessionStart`.
  - The other arms have no hooks.
- **memkernel server:** a compaction session is 4 Claude Code invocations
  (exposure, work, `/compact`, evaluation) and any other session is 1. The
  arm's 8 sessions therefore make 14 invocations, and the server reported
  `connected` in all 14.

### Token usage by arm (receipts, excluding `/compact` steps)

| Arm | Sessions | Input | Cache write | Cache read | Output | Total | Per session, min / median / max | Wall time per session, median / max |
|---|---|---|---|---|---|---|---|---|
| `bare` | 8 | 90 | 131,632 | 854,711 | 11,242 | 997,675 | 54,720 / 74,006 / 290,070 | 11.0 s / 40.9 s |
| `claude_md` | 8 | 90 | 119,281 | 867,431 | 11,234 | 998,036 | 54,323 / 73,924 / 290,196 | 11.6 s / 43.4 s |
| `fs_grep` | 8 | 92 | 132,201 | 914,996 | 12,501 | 1,059,790 | 73,751 / 87,809 / 290,720 | 12.1 s / 40.4 s |
| `memkernel` | 8 | 90 | 128,764 | 906,227 | 10,319 | 1,045,400 | 56,969 / 77,604 / 299,861 | 17.2 s / 81.4 s |
| `placebo` | 8 | 90 | 125,130 | 887,412 | 12,912 | 1,025,544 | 56,993 / 75,078 / 296,560 | 11.8 s / 47.2 s |
| `protocol` | 8 | 90 | 124,761 | 893,954 | 11,854 | 1,030,659 | 57,369 / 75,822 / 298,562 | 11.5 s / 42.5 s |
| `wiki_studio` | 2 | 18 | 15,543 | 156,154 | 2,653 | 174,368 | 77,259 / 87,184 / 97,109 | 13.1 s / 14.9 s |
| **All** | 50 | 560 | 777,312 | 5,480,885 | 72,715 | **6,331,472** | 54,323 / 75,822 / 299,861 | 12.2 s / 81.4 s |

Per group, the total tokens per session (min / median / max), excluding the
`/compact` steps, are as follows. The `lc-compact` row undercounts the most:
each of those sessions also had one compaction call of 35,999–37,220 input
tokens.

| Group | Sessions | Min | Median | Max |
|---|---|---|---|---|
| `lc-compact` | 12 | 269,218 | 293,210 | 299,861 |
| `lc-retain` | 12 | 54,323 | 73,501 | 97,129 |
| `lc-reval` | 12 | 56,969 | 73,973 | 78,489 |
| `lc-wiki` | 14 | 72,699 | 76,542 | 99,620 |

### Receipts undercount the compaction calls

| | Input (all input classes) | Output |
|---|---|---|
| Console | 6,719,191 | 91,983 |
| Receipts | 6,258,757 | 72,715 |
| Missing from the receipts | 460,434 (6.9%) | 19,268 (20.9%) |

**Cause.** In all 12 compaction sessions, the result of the `/compact` step
reports 0 tokens. Yet each `compact_boundary` event records a real model call:
`pre_tokens` is between 35,999 and 37,220, and each call takes 8.6–16.4 s. The
12 `pre_tokens` sum to 438,613, which accounts for most of the missing input.
The remaining 21,821 input tokens (about 5% of the gap) are unexplained, so the
compaction-token PR is not expected to close the whole gap. The missing output
is most likely the compaction summaries, which no stream field counts; that is
not measured.

**Consequences:**
- The measured run's budget must use the Console's figures, or the receipts
  plus the compaction calls; the receipts alone underestimate `lc-compact`.
- Billing figures come only from the Console.
- The fix belongs in its own PR: the receipts will carry
  `compact_metadata.pre_tokens`, labelled as an estimate. That PR must land
  before the measured run, so that the measured receipts are complete.

## Observations

These are stated, not tuned against. Any change to an arm or a task must be
documented and followed by a new calibration before the freeze (FR-015).

1. **The memkernel arm never used the wiki bridge.**
   - None of its sessions called `wiki_export` or `wiki_import`.
   - It called `retain` once in each exposure session.
   - Its evaluation sessions made no memkernel calls (`recall_to_use` 0/0);
     only its `SessionStart` hook ran there.
   - The receipts hold hashes and counts, not content, so whether that hook
     brought the fact back into context can't be seen.

   The run therefore shows that the integration ran, not that the
   export/import mechanism works. Task 18a checks that mechanism (below).
2. **How each arm wrote the wiki on `lc-wiki-backoff`:**
   - `memkernel`, `claude_md`, `fs_grep` and `placebo` wrote the page with
     Write or Edit;
   - `bare` and `protocol` wrote it through Bash;
   - `wiki_studio` wrote it through its CLI.
3. **`wiki_studio` diagnostics:** no nested-model invocations and no direct
   wiki Write or Edit calls were detected (`wiki_studio_nested_model_calls`
   0/7, `direct_wiki_writes` 0/1). The detector is a best-effort static count
   with known blind spots: a wiki write made through Bash is not counted as a
   direct write.
4. **memkernel's sessions take longer:** a median of 17.2 s per session,
   against 11.0–12.1 s for the other main arms.

## Wiki-bridge wiring check (task 18a)

**Result:** it passed, 14 of 14 steps, in the calibrated image on 2026-10-20
UTC, using `vm.sh wiring`.

**What ran:**
- Image: ID `sha256:ba4dc322…`, image code `12a3ff3`.
- Check: commit `dec8ad70cde3ba46007304a4f6ab035d31170989`, clean, copied with
  `git archive`. `wiring_check.py` sha256
  `84ee944463ec52fe19aa65a644cc4136b0043ef2b71b966653d7aae699f4a3f0`.
- `eval/lifecycle-suite/` outside `wiring/` and `calibration/` is identical at
  the two commits.

**What it showed:**
- **Source namespace:** the store went from 0 records to 1, and `wiki_export`
  wrote exactly one page.
- **Transfer:** every fixture file reached the destination workspace, and
  those outside the wiki were byte-identical. Only `knowledge/wiki/` crossed:
  the page and `log.md`, which `wiki_export` writes.
- **Destination namespace:** a second namespace whose store started with 0
  records, and `recall` found nothing. `wiki_import` imported the page, and the
  store then held exactly that page. `get` returned the synthetic sentence
  verbatim.

The wiki bridge therefore works in the calibrated runtime, image
`sha256:ba4dc322…`. No fix was needed, so 18a by itself doesn't call for a new
calibration. If the runtime changes (open item 1, option A), 18a is re-run on
the new image before it is ticked.

## Open items

1. **The memkernel server contacts Hugging Face at startup (option A
   chosen).**
   - **What happens:** in the wiring check, each of the 3 server starts sent
     HEAD and GET requests to huggingface.co for
     `sentence-transformers/all-MiniLM-L6-v2` at `resolve/main`, although the
     model is in the image. They resolved revision `1110a243…`.
   - **The risk:**
     - the server depends on the network at every session start;
     - if Hugging Face publishes a newer revision of the model, the embedding
       model could change between calibration and the measured run.
   - **Option A, fix it (chosen 2026-10-20 UTC):**
     1. set `HF_HUB_OFFLINE=1` in the server environment the runner gives the
        memkernel arm, and pin the model revision in the image's cache.
        **Done in #38:** the runner also refuses a calibration or measured run
        without the shared cache, the build fails on any other revision, and
        preflight prints the revision;
     2. build a new image;
     3. recalibrate, about $3.53 again (FR-015: a runtime change is documented
        and followed by a new calibration before the freeze);
     4. re-run 18a on the new image, then tick it.
   - Option B, keeping the runtime and stating the dependency in the
     preregistration, was not chosen: it would leave an outside dependency that
     changes over time inside a preregistered run.
2. **Compaction calls in the receipts (done by task 18b):** receipts now carry
   `compaction_tokens_estimate`, the sum of `compact_boundary.pre_tokens`, an
   estimate of the compaction calls' input only, kept out of the token
   classes. On this run's streams it sums to 438,613, as above; the 21,821
   remaining input tokens stay unexplained.
3. **The VM can reach the Mac (addressed for the recalibration by the host
   block in `vm.sh`).** The block rejects every private, link-local and CGNAT
   destination by address, with no port. `preflight` and `calibrate` reapply it
   and require TCP probes on four ports to the gateway, the Mac's addresses and
   two LAN addresses to fail, each one counted (as user `nobody`, by a rule
   that sees only the probes) on its way to the reject rule, and then the same
   from a throwaway container of the selected image, where the agent runs;
   the block also rejects connections to the VM's own non-loopback addresses; `vm.sh check`
   reports the same probes. That shows the rule is loaded and effective, not
   that every port was tried. Through `host.lima.internal`, the agent's
   Bash tool could reach any service listening on the Mac, which the
   disposable-machine requirement is meant to rule out. Which services were
   listening during this run was not recorded. For the recalibration, either
   block the VM from reaching the host and have `vm.sh check` prove it, or
   record it in the preregistration as a known exception, listing the
   services that were listening.
4. **wiki-studio is installed without a hash check (done in #38).** The image installs
   exactly `wiki-studio==0.4.1`, the version in `poetry.lock`, and the runner
   refuses any other. wiki-studio 0.4.1 has no dependencies of its own (pip
   resolves it alone, and the lock lists none). But it goes into its own venv
   without `--require-hashes`, and `environment.txt` records only the
   `# wiki-studio 0.4.1` line, not that venv's packages. For the new image,
   install it with the locked hashes and record that venv's `pip freeze` in
   `environment.txt`.
5. **Freeze:** tasks, arm configurations and the preregistration are frozen
   after the new calibration and 18a pass on its image (task 18's last step,
   then task 19).

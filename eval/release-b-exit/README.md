# The Release B exit run

The exit evidence for Release B, from #48: "one complete correction loop (retain, export, review, import,
correct, next-session recall) on clean installs with compatible versions, surviving retries". The plan and the
owner's decisions are in [`specs/memkernel-0-7-release-b-exit/`](../../specs/memkernel-0-7-release-b-exit/plan.md).

## `run.py`: the two runs

Both runs work on one persisted memkernel store and one governed wiki under `--workdir`, which must be empty.
Each step is its own process, and memkernel runs in `MEMKERNEL_WIKI_MODE=governed`. The interpreter must have
memkernel, wiki-studio and the `wiki-studio` CLI beside it. No model backend is used on any path; the only model
is memkernel's local embedding model.

### The main run: `python run.py --workdir DIR [--summary PATH]`

| Step | What it does |
|------|--------------|
| `session-1` | Initialises a governed wiki and retains five decisions, one of them wrong. It exports them through the gate as five drafts (`remaining` 0, each with a `page_id`), and the session-start block shows `unapproved 5` under the curation debt. |
| `curator-1` | Uses the wiki-studio CLI to correct the wrong page (`corrects:`), make the rest stable, propose and promote them (guarded, with `.base.json`), and approve all five. |
| `session-2` | **R4:** two imports at once. The first holds the store's import lock after its first write. The second writes a marker when its import asks for the lock, after the import's preflight, and the first is released only after that marker plus a 1 s hold. The second must take the lock only after the release. Then the convergence checks run. |
| `session-2-again` | **R3:** export and import again change nothing; the convergence summary is identical. |
| `curator-2` | **R1:** the successor page's promote commits, then its archive step fails, and promoting again resolves from the receipt with nothing re-applied. Then it deprecates one page, marks one superseded by the successor, edits one, and deletes one (file and index entry). |
| `session-3-killed` | **R2:** the import is killed (`os._exit`) between the edited page's replacement write and its predecessor's supersession mark (wiki-scope S3). |
| `session-3` | Checks both records are live after the kill. The next import completes the supersession, withdraws the deprecated and the deleted pages' memories, and supersedes the old page by its successor. Then the convergence checks run. |
| `session-4` | The next session. The start block has no wrong rule and no unapproved debt; recall answers with the corrected page, whose `page_sha:` is the approved revision. |

### The upgrade run: `python run.py --upgrade --upgrade-to REQ --workdir DIR [--summary PATH]`

It starts in an environment holding memkernel 0.6.0.

| Step | What it does |
|------|--------------|
| `u-session-0` | On memkernel 0.6.0, retains two decisions, exports them, approves them through the curator and imports them: a store that 0.6.0 itself wrote. |
| (upgrade) | `pip install --no-deps --force-reinstall REQ`: the 0.7.x wheel. |
| `u-session-1` | The first 0.7 import lists both pages as `ambiguous` (`legacy owner unproven`) and changes no memory. |
| `u-session-2` | `adopt_legacy=true` adopts each record once, giving it the wiki's identity, with no new record. |
| `u-curator`, `u-session-3` | One correction through the 0.7 loop, the recall in a new process, and the convergence checks. |

### Faults and convergence

Faults are injected only inside a step's own process, by wrapping a function before the step calls memkernel or
wiki-studio. The installed packages' files are never patched. R2 wraps the private
`MemoryService._mark_superseded`, R4 wraps `retain` and `exclusive`, and R1 wraps wiki-studio's private
`promoter._archive_submission`, checking that the archive actually failed. Each depends on how its release
implements these, so a run is tied to the releases it records.

The convergence checks are:
- the expected live pages, each with one live memory holding its rule;
- the retired records kept (superseded or withdrawn);
- no page key with two live memories;
- no duplicate page or receipt;
- no unfinished ledger entry.

The expected end state is written in `run.py`, not taken from a second run.

Exit codes: 0 when every check passes; 1 when a check fails, with one line naming it; 2 when the run cannot
start.

## `record.py`: the recording protocol

This follows wiki-studio's protocol (`examples/correction-loop/README.md` at wiki-studio
`2d5bf033d00fb7c57b1e1d3932a7586497bea9fb`), with released wheels on both sides.

1. **Commit first.** `run.py`, `record.py` and this README are committed before any recorded run.
2. **A clean tree.** `record.py` refuses unless `git status --porcelain` is empty. It records `HEAD`'s full SHA,
   extracts that commit, and runs only from it; it refuses if the running `record.py` differs from the committed
   one.
3. **Released wheels, Python 3.11.** `record.py --memkernel X --wiki-studio Y [--upgrade]` runs only under
   Python 3.11 and refuses any other interpreter. It downloads the wheels from PyPI and refuses any whose sha256
   differs from the one PyPI publishes; the upgrade run also downloads memkernel 0.6.0. It installs them into a
   fresh virtual environment and records `pip freeze`: `environment.txt` for the main run;
   `environment-before.txt`, `environment-after.txt` and a post-upgrade `pip check` for the upgrade run. A failed
   `pip check` is the named check `pip-check-after-upgrade` in the manifest's checks, and fails the attempt (exit
   code 1) even when every check of the run passed; a run that already failed keeps its own, higher exit code. The
   embedding model is pinned in `record.py` (`sentence-transformers/all-MiniLM-L6-v2` at
   `1110a243fdf4706b3f48f1d95db1a4f5529b4d41`); no option overrides it, and any other snapshot is refused. The run
   happens once, never retried, with the hub offline.
4. **A failed attempt is kept.** `manifest.json` exists from the moment `--out` is created, with `outcome:
   running` and the stage. Every rewrite is atomic (a temporary file, fsynced, then renamed), so an interruption
   leaves the previous manifest whole. It ends as `completed`, with the run's exit code, every check and the
   convergence summary, or as `failed`, with the stage and the error. A second attempt is a new directory.

   The two recorded runs, from the repository root, once the versions are on PyPI. The recorder refuses an
   unclean tree, so each run is committed before the next one starts:

   ```bash
   # 1. The main run, then read its manifest.json and transcript.txt.
   python3.11 eval/release-b-exit/record.py --out eval/release-b-exit/runs/<date>-memkernel-0.7.0-wiki-studio-0.8.1 \
     --memkernel 0.7.0 --wiki-studio 0.8.1
   git add eval/release-b-exit/runs/<date>-memkernel-0.7.0-wiki-studio-0.8.1
   git commit -m "Release B exit run: memkernel 0.7.0, wiki-studio 0.8.1"
   git status --porcelain   # must print nothing before the next run

   # 2. The upgrade run, then read its manifest.json, transcript.txt and the two environment files.
   python3.11 eval/release-b-exit/record.py --upgrade \
     --out eval/release-b-exit/runs/<date>-upgrade-memkernel-0.6.0-to-0.7.0-wiki-studio-0.8.1 \
     --memkernel 0.7.0 --wiki-studio 0.8.1
   git add eval/release-b-exit/runs/<date>-upgrade-memkernel-0.6.0-to-0.7.0-wiki-studio-0.8.1
   git commit -m "Release B upgrade run: memkernel 0.6.0 to 0.7.0, wiki-studio 0.8.1"
   ```
5. **Commit the run directory alone**, under `eval/release-b-exit/runs/<date>-memkernel-<v>-wiki-studio-<v>/`, or
   `runs/<date>-upgrade-memkernel-0.6.0-to-<v>-wiki-studio-<v>/`, and never edit it afterwards.

If a recorded run finds a defect, that attempt is kept as it is. The fix ships as the next patch release, and the
new attempt is a new directory naming it. The exit evidence is the first released 0.7.x that passes, with the
wiki-studio release it ran with. The owner runs the recorded runs.

## CI

`.github/workflows/release-b-exit.yml` runs both runs against a wheel built from the pull request and the newest
wiki-studio below 1.0. It runs on pull requests that change `src/memkernel/**`, `eval/release-b-exit/**` or the
workflow, weekly, and by dispatch. It is informational, not a required check. A green run is a signal on a
wheel built from the PR; the exit evidence is only the recorded runs on released wheels.

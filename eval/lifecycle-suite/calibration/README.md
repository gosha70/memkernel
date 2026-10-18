# Calibration run (task 18)

The calibration run of `specs/memkernel-0-5` FR-015 happens in a disposable
container. It runs every arm on the five tasks in `tasks.txt` on the approved
model (`claude-sonnet-5-5`), measures token usage per arm, and shows whether
Claude Code compacts live with the `PreCompact`/`PostCompact` hooks
recorded. Nothing is graded. After each chain, the runner deletes everything
except the receipts and raw streams.

The image holds one commit, from `git archive`. Its Python dependencies are installed from that commit's `poetry.lock` with hashes, except torch, which is the locked version from PyTorch's CPU index, without its CUDA packages. It also holds pinned tools:
- Claude Code 2.1.288
- wiki-studio 0.4.1
- memkernel and its embedding model, downloaded at build time

Only `/runs` is mounted. The API key goes in with `docker run` and is never
built into the image.

## 1. Before you start

1. **Machine.** Use a machine or VM that holds no personal credentials: no
   `~/.ssh`, `~/.aws`, git or cloud credentials, and no other API keys. The
   agent's Bash tool runs inside the container, but treat the host as
   exposed too.
2. **Workspace.** In the Claude Console, under Settings → Workspaces, create a
   new workspace just for this run, for example `memkernel-calibration`. Don't
   use the Default Workspace, which can't carry limits, or the Claude Code
   workspace. Note its `wrkspc_…` ID.
3. **Spend limit.** Open the workspace, click **Spend limits**, set the
   monthly limit to **$30**, then check that the Console shows that limit. This
   limit, not the key, is the cap. If another paid run used a workspace this
   month, create a new one.
4. **Key.** Create a new API key in that workspace only.

## 2. Build

Build from a clean checkout of the commit that will be calibrated:

```bash
eval/lifecycle-suite/calibration/build.sh      # tags memkernel-calibration:<sha12>
```

## 3. Check, then run

```bash
mkdir -p calibration-runs
sudo chown 1000:1000 calibration-runs          # Linux: the container runs as uid 1000 (not needed on Docker Desktop)
export ANTHROPIC_API_KEY=...                    # the new key; never written to a file
export CALIBRATION_WORKSPACE_ID=wrkspc_...      # the dedicated workspace
docker run --rm --tmpfs /tmp:rw,size=1g -e ANTHROPIC_API_KEY -e CALIBRATION_WORKSPACE_ID \
  -v "$PWD/calibration-runs:/runs" memkernel-calibration:<sha12> preflight
```

`preflight` spends nothing. It prints the code SHA, the tool versions and the sha256 of the image's resolved environment, and writes a probe file to `/runs`. It
then lists models with the key and checks the response's
`anthropic-workspace-id` header against `CALIBRATION_WORKSPACE_ID`, and refuses
on any mismatch or rejected key. Once it passes, run:

```bash
docker run --rm --tmpfs /tmp:rw,size=1g -e ANTHROPIC_API_KEY -e CALIBRATION_WORKSPACE_ID \
  -v "$PWD/calibration-runs:/runs" memkernel-calibration:<sha12> calibrate
```

`--tmpfs /tmp` keeps the agent's scratch files, such as the `wiki_studio`
arm's `mktemp -d` drafts, in memory, where they vanish with the container.

`calibrate` runs `preflight` again, then the runner (`--phase calibration`,
all seven arms, `wiki_studio` on `lc-wiki` only), then `scan_secrets.py` over
the run. The scan also runs when the runner fails, over whatever output exists, and the exit status is the runner's, or the scan's if the runner succeeded. `environment.txt` (the image's `pip freeze` and tool versions) is copied into the run directory. The runner also refuses to start unless `wiki-studio --version`
reports 0.4.1. `demo` runs the credential-free stub demonstration in the same
image and needs no key.

Rebuild the image from the commit being calibrated right before the run. The
image holds its own copy of `run.sh`, so an older image runs older scripts.
`build.sh` builds only a clean commit, so the receipts' `code_sha` identifies
the image's code, and `environment.txt` in the run records `run.sh`'s sha256.
Record the image ID with the calibration record:
`docker image inspect --format '{{.Id}}' memkernel-calibration:<sha12>`.
The run must print no `WARNING: image paths overridden` line, and the run
directory must contain no `overrides.txt`. Those overrides exist for the
script's tests only.

## 4. Afterwards

1. Revoke the key, then archive the workspace, which archives every key in
   it. Note the date for the report (FR-018).
2. Review `calibration-runs/<run id>/` yourself, including the secret-scan
   output, before anything from it is committed.
3. Record the configuration, cost and exclusion reasons (FR-015). The cost is
   in the Console's usage for that workspace.

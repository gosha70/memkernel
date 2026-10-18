# Calibration run (task 18)

The calibration run of `specs/memkernel-0-5` FR-015 runs every arm on the five
tasks in `tasks.txt` on the approved model (`claude-sonnet-5-5`). It measures
token usage per arm and shows whether Claude Code compacts live with the
`PreCompact`/`PostCompact` hooks recorded. Nothing is graded. After each chain,
the runner deletes everything except the receipts and raw streams.

## Where it runs, and why

During the run, Claude Code works as an agent with a Bash tool. It runs
commands it chooses itself, on files and prompts from the task fixtures. A
fresh `HOME` does not stop it reading any file by its full path. FR-015
therefore requires an environment with **no personal credentials in reach**,
thrown away afterwards: no `~/.ssh`, `~/.aws`, git or cloud credentials, and no
other API keys. The only secret present is the calibration key, whose
workspace caps the spend.

The run always happens in the **calibration container**, which this directory
builds. Where that container runs is your choice:

| Where the container runs | Isolation from your files | Use it |
|---|---|---|
| **A throwaway local Lima VM on your Mac** (section 3) | separate Linux kernel; the VM shares no folders with the Mac | recommended |
| Docker directly on a Linux host or cloud VM that you delete afterwards (section 4) | container only, or a whole separate VM | if you already have one |

A conda environment or a Python venv does **not** isolate anything. It
only selects packages, and the agent would still run as you, with your files.

## The container

The image holds one commit, taken with `git archive`. Its Python dependencies
are installed from that commit's `poetry.lock` with hashes. The one exception
is torch: the locked version, but the CPU build from PyTorch's index, without
its CUDA packages. It also holds pinned tools:
- Claude Code 2.1.288
- wiki-studio 0.4.1
- memkernel and its embedding model, downloaded at build time

Inside the container, the agent sees only `/runs`. The API key arrives when the
container starts and is never built into the image.

Entry point modes (`run.sh`):
- **`demo`:** the credential-free stub demonstration. No key, spends nothing.
- **`preflight`:** spends nothing. It prints the code SHA, the tool versions and
  the sha256s of `run.sh` and of the resolved environment. It writes a probe
  file to `/runs`, then lists models with the key, which is free, and checks the
  response's `anthropic-workspace-id` header against the workspace ID. It
  refuses on a mismatch, a rejected key or an unwritable `/runs`.
- **`calibrate`:** runs `preflight` again, then the runner (`--phase calibration`,
  all seven arms, `wiki_studio` on `lc-wiki` only), then `scan_secrets.py`.
  - The scan also runs when the runner fails, over whatever output exists. The
    exit status is the runner's, otherwise the scan's.
  - A scan hit always prints `SECRET SCAN FOUND HITS … do not commit`.
  - `environment.txt`, the image's `pip freeze` and tool versions, is copied
    into the run.
  - The runner refuses to start unless `wiki-studio --version` reports 0.4.1.

The run must print no `WARNING: image paths overridden` line, and the run
directory must contain no `overrides.txt`. Those overrides exist for the
script's tests only.

## 1. Before you start: the workspace and the key (Claude Console)

1. **Workspace.** Under Settings → Workspaces, create a new workspace just for
   this run, for example `memkernel-calibration`. Don't use the Default
   Workspace, which can't carry limits, or the Claude Code workspace. Note its
   `wrkspc_…` ID.
2. **Spend limit.** Open the workspace, click **Spend limits**, set the monthly
   limit to **$30**, then check that the Console shows it. This limit, not the
   key, is the cap. If another paid run used a workspace this month, create a
   new one.
3. **Key.** Create a new API key in that workspace only. Keep it out of files
   and shell history: `vm.sh` asks for it at a hidden prompt.

## 2. What to record (FR-018)

- the image tag and image ID (`vm.sh build` prints both);
- the environment you used (for example "local Lima VM, no shared folders");
- the workspace ID and its verified spend limit;
- the date you revoked the key and archived the workspace.

## 3. Run it in a throwaway local Lima VM (recommended)

[Lima](https://lima-vm.io) runs a Linux VM on your Mac. `vm.sh` creates one
named `mk-calibration` with **no shared folders** (`--mount-none`), no SSH
agent forwarding and no X11 forwarding, and with rootless Docker inside. Your
Mac's files are not visible in it. The VM gets the code by cloning the public
repository at the exact commit. The key is typed at a hidden prompt and passed
to the VM on stdin. It is never written to a file or shown on a command line,
and your Mac's environment is never forwarded into the VM.

The VM can still open network connections to services listening on your
Mac (through `host.lima.internal`). Stop local services that hold sensitive
data while the run is going, or use a cloud VM (section 4).

Steps, from a checkout of this repository on your Mac:

```bash
brew install lima                                   # once
V=eval/lifecycle-suite/calibration/vm.sh

$V create        # a few minutes: downloads Ubuntu, installs Docker in the VM
$V check         # expect: no shared folders, no /Users path, no credentials, no SSH agent
$V build 35b2ff0 # clones the repo at that commit inside the VM, builds the image (about 10 min);
                 # prints the image tag and ID; record them
$V demo          # expect: "demo: 32 receipts, 32 sessions observed, 0 failure(s)"
$V preflight     # asks for the key (hidden) and the workspace ID; spends nothing;
                 # expect "workspace: wrkspc_... (matches CALIBRATION_WORKSPACE_ID)"
$V calibrate     # the paid run: type 'calibrate', then the key and workspace ID again.
                 # It runs in the foreground; keep the Mac awake (for example: caffeinate -i $V calibrate)
$V fetch         # copies the VM's runs to ./calibration-runs on your Mac
$V destroy       # deletes the VM and everything in it
```

Build from the commit you calibrate (`35b2ff0`, or a later `main` if it moved).
The image holds its own copy of `run.sh`, and `build.sh` builds only a clean
commit, so the receipts' `code_sha` identifies the image's code.

If something fails part-way, `$V destroy` and start again from `$V create`.
Nothing in the VM is worth keeping except what `$V fetch` copies.

## 4. Run it with Docker directly (Linux host or cloud VM)

On a Linux machine or cloud VM that holds no personal credentials and that you
delete afterwards:

```bash
git clone https://github.com/gosha70/memkernel.git && cd memkernel && git checkout 35b2ff0
eval/lifecycle-suite/calibration/build.sh            # tags memkernel-calibration:<sha12>
docker image inspect --format '{{.Id}}' memkernel-calibration:<sha12>   # record it
mkdir -p calibration-runs && sudo chown 1000:1000 calibration-runs      # the container runs as uid 1000
read -r -s -p "API key: " ANTHROPIC_API_KEY && export ANTHROPIC_API_KEY && echo
export CALIBRATION_WORKSPACE_ID=wrkspc_...
docker run --rm --tmpfs /tmp:rw,size=1g -e ANTHROPIC_API_KEY -e CALIBRATION_WORKSPACE_ID \
  -v "$PWD/calibration-runs:/runs" memkernel-calibration:<sha12> preflight
docker run --rm --tmpfs /tmp:rw,size=1g -e ANTHROPIC_API_KEY -e CALIBRATION_WORKSPACE_ID \
  -v "$PWD/calibration-runs:/runs" memkernel-calibration:<sha12> calibrate
```

`--tmpfs /tmp` keeps the agent's scratch files, such as the `wiki_studio`
arm's `mktemp -d` drafts, in memory, where they vanish with the container.

## 5. Afterwards

1. Revoke the key, then archive the workspace, which archives every key in it.
   Note the date for the report (FR-018).
2. Delete the VM (`vm.sh destroy`, or delete the cloud VM).
3. Review `calibration-runs/<run id>/` yourself, including the secret-scan
   output, before anything from it is committed.
4. Record the configuration, cost and exclusion reasons (FR-015). The cost is
   in the Console's usage for that workspace.

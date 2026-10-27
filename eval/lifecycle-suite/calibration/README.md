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
- wiki-studio 0.4.1, the `wiki_studio` arm's pin with its hashes
  (`arms/wiki_studio/requirements.txt`), independent of memkernel's `poetry.lock`
- memkernel and its embedding model, downloaded at build time

Inside the container, the agent sees only `/runs`. The API key arrives when the
container starts and is never built into the image.

Entry point modes (`run.sh`):
- **`demo`:** the credential-free stub demonstration. No key, spends nothing.
- **`preflight`:** spends nothing. It prints the code SHA, the tool versions and
  the sha256s of `run.sh` and of the resolved environment. It checks that the
  image's cache holds the pinned embedding model revision and prints it: the
  memkernel server runs offline (`HF_HUB_OFFLINE=1`), so the model can come
  only from that cache. It writes a probe file to `/runs`, then lists models
  with the key, which is free, and checks the response's
  `anthropic-workspace-id` header against the workspace ID. It refuses on a
  missing or different cached revision (before the key is used), a mismatch, a
  rejected key or an unwritable `/runs`.
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

All of this happens in the **Claude Console**, Anthropic's API website at
https://platform.claude.com. It is not in the Claude Desktop app or claude.ai.

1. **Workspace.** In the Console, open **Settings** (in the left navigation),
   then **Workspaces**, and create a new workspace just for this run, for example `memkernel-calibration`. Don't use the
   Default workspace, which can't carry limits, or the Claude Code workspace.
   Its ID is shown in the workspace list and in the workspace's panel: `wrkspc_`
   followed by letters and digits.
2. **Spend limit.** Open the workspace, click **Spend limits**, set the monthly
   limit to **$30**, then reopen it and check that the Console shows $30.00.
   This limit, not the key, is the cap. If another paid run used a workspace
   this month, create a new one.
3. **Key.** Create a new key in that workspace: Settings → Workspaces, click
   the workspace, then the **API keys** link in its panel. It starts with
   `sk-ant-` and is shown only once. Keep it out of files and shell history:
   `vm.sh` asks for it at a hidden prompt.

`preflight` checks that the key belongs to the workspace ID you type, but it
cannot tell a dedicated workspace from Default: a Default key with Default's ID
passes. Before `calibrate`, check that the `workspace:` line shows the ID of the
workspace you created, not Default's.

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

Lima's network would let the VM reach services listening on your Mac (through
`host.lima.internal`, or the Mac's own addresses) and the rest of your LAN.
`vm.sh create` therefore installs a **host block**: a firewall table in the VM,
loaded at every boot, that lets the VM send only DNS and DHCP to Lima's gateway
and rejects every private, link-local and CGNAT destination. It covers the
containers too, because rootless Docker's traffic leaves through the VM. It also
rejects connections to the VM's own addresses other than loopback, so a
container can't reach the VM's own services, such as its `sshd`. The
internet stays reachable, which the run needs for the Anthropic API.
Connections from the Mac into the VM, which `limactl shell`, `copy` and port
forwarding use, are unaffected.

The block accepts established traffic first, which its own reject replies need.
So it holds only for connections opened after it was loaded. `vm.sh create`
installs it as a unit that loads at every boot, before the network and before
Docker, so no container ever starts without it. Don't add it to a VM that is
already running work. If `vm.sh check` ever reports the block missing, delete
the VM and create a new one: reapplying the rules stops new connections, but
any connection opened while the block was missing would stay open.

Before asking for the key, `vm.sh preflight` and `vm.sh calibrate` reapply the
block from `vm.sh`'s own copy (undoing any change to it) and probe TCP ports 22,
80, 443 and 8080 on Lima's gateway, the Mac's addresses and two LAN addresses.
The probes run as the unprivileged `nobody` user, and a counting rule just
before the reject sees only that user's packets. Every probe must fail with "No
route to host" while that counter rises, which shows the reject rule stopped
that probe, or they refuse. Because the agent runs in the container, they then
repeat the probes from a throwaway container of the selected image, run with
the real run's flags. Each probe must fail while the matching counter rises:
the VM user's counter for the Mac and LAN addresses (rootless Docker's network
helper runs as that user), the own-address rule's counter for the VM's own
addresses. They also try `10.0.2.2`, the VM's loopback as the helper would map
it, which rootless Docker's `--disable-host-loopback` blocks. `vm.sh check`
runs the container probes once an image is built. The rule matches by address alone, so the probes
show that it is loaded and effective; they do not try every port.

Steps, from a checkout of this repository on your Mac:

```bash
brew install lima                                   # once
V=eval/lifecycle-suite/calibration/vm.sh

$V create        # a few minutes: downloads Ubuntu, installs Docker in the VM
$V check         # expect: no shared folders, no /Users path, no credentials, no SSH agent;
                 # every host-block probe "blocked" and counted by its rule, the API "HTTP 401",
                 # copy and port forwarding "ok"; it ends "every host-block probe failed as its line requires" or exits 1
$V build <sha>   # the main commit to calibrate; clones the repo at it inside the VM, builds the image (about 10 min);
                 # prints the image tag and ID; record them
$V demo          # expect: "demo: 32 receipts, 32 sessions observed, 0 failure(s)"
$V preflight     # asks for the key (hidden) and the workspace ID; spends nothing;
                 # expect "workspace: wrkspc_... (matches CALIBRATION_WORKSPACE_ID)" with your new
                 # workspace's ID, not Default's
$V calibrate     # the paid run: type 'calibrate', then the key and workspace ID again.
                 # It runs in the foreground; keep the Mac awake (for example: caffeinate -i $V calibrate)
$V fetch ~/memkernel-calibration-runs   # copies the VM's runs there and verifies every file (sha256);
                 # expect "copied and verified N file(s)". Keep the copy outside this checkout:
                 # the default, ./calibration-runs, is inside it and not ignored by git
$V save-image    # copies the calibrated image to ~/memkernel-calibration-image-<id>.tar.gz, verified;
                 # the only other copy is inside this VM; the archive is then removed from the VM's disk
$V wiring        # the credential-free wiki-bridge wiring check (below), on that same image
$V destroy       # deletes the VM; refuses while it holds runs that were not fetched and verified
```

Build from the `main` commit you calibrate (`git rev-parse HEAD` after `git pull`).
The image holds its own copy of `run.sh`, and `build.sh` builds only a clean
commit, so the receipts' `code_sha` identifies the image's code.

**If something fails part-way, fetch before anything else.** A failed or
interrupted calibration can already hold receipts, raw streams and partial
results, and the report needs them (FR-015, FR-018). The order is always:

1. `$V fetch`. It must end with "copied and verified N file(s)". If it reports
   a mismatch or a missing file, or fails at all, **keep the VM** and run
   `$V fetch` again, to a fresh directory if needed, until it succeeds.
2. Check the local copy yourself: `ls -R calibration-runs`.
3. Only then `$V destroy`, and start again from `$V create` if you need to.

`$V destroy` enforces this. It refuses while the VM's runs differ from the
last verified fetch. `$V destroy --discard` overrides it and throws those runs
away, so use it only when you are sure nothing in them is needed.

### Wiki-bridge wiring check (task 18a)

Calibration showed that the memkernel arm ran, but it never called
`wiki_export` or `wiki_import`. So it does not show that the export and import
mechanism works. `$V wiring` checks that mechanism directly. It uses no key, no
model and no agent, and its fixture (`eval/lifecycle-suite/wiring/fixture/`) is
synthetic, unrelated to any measured task.

The check is mounted **read-only into the calibrated image** with an overridden
entrypoint, so the image is unchanged. It runs that image's own runner and
memkernel against the real MCP server over stdio:
1. **Source namespace.** It counts 0 records, `retain`s a synthetic decision,
   runs `wiki_export`, then counts 1 record.
2. **Transfer.** The runner's own `prepare_session` moves the wiki under the
   memkernel arm's frozen rule. Only `knowledge/wiki/` may cross: a
   `NOTES.md` left in the source workspace must not. Every fixture file must
   still be there, and those outside the wiki must stay byte-identical. Files
   under `knowledge/wiki/` are not judged: the arm's rule carries that directory
   over whole, by design.
3. **Destination namespace.** It counts 0 records (with memkernel's library,
   not by searching) and checks that `recall` finds nothing. Then it runs
   `wiki_import`, counts exactly the imported pages, and checks that `get`
   returns the synthetic sentence verbatim.

`$V wiring` refuses to run while `eval/lifecycle-suite/wiring/` has uncommitted
changes, and copies that directory from the commit itself (`git archive`), so
the commit it prints is exactly the check that ran. It also refuses when
anything else under `eval/lifecycle-suite/` (runner, arms, tasks) differs
between the image's commit and that commit, because the check calls the image's
runner directly; only `wiring/` and `calibration/` may differ. It prints the image ID, the
image's code SHA, the check's commit and `wiring_check.py`'s sha256, then one
JSON object with every step. It passes
only when every step does. If it fails and the fix needs a change to the
runtime, a task or an arm, document the fix and calibrate again before the
freeze.

A later VM can get the same image back with `$V create` and then
`$V load-image ~/memkernel-calibration-image-<id>.tar.gz`, which checks the image ID.

### The measured run (task 20)

The same VM and the same image run the measured run, after the code freeze, the
preregistration commit and `PREREG_COMMIT` are on `main` and announced on #17
(task 19). Build the image at the code-freeze commit, then:

```bash
git switch main && git pull          # HEAD must hold eval/lifecycle-suite/PREREG_COMMIT
caffeinate -i $V measure https://github.com/gosha70/memkernel/issues/17#issuecomment-<id>
```

The URL is the #17 comment that announced the preregistration: open the comment
on GitHub, click its timestamp, and copy the address bar.

`$V measure` refuses unless the commit `PREREG_COMMIT` names adds only
`eval/lifecycle-suite/preregistration.md` to the image's commit, and unless
that comment, read through GitHub's public API, is on #17 and names that commit
and the file's sha256. It prints the commit, the sha256 and when the comment was
posted and last edited (with a warning if it was edited), and records the URL
and both times in the run as `announcement.txt` (SC-5). It copies that file into the VM and mounts it
read-only. After you type `measure`, it asks for the key and the workspace ID,
as for calibration, and then for the workspace's spend limit in dollars: read it
in the Claude Console (https://platform.claude.com, Settings → Workspaces → the
measured run's workspace → Spend limits) and type the number, for example `150`.

Before any paid session, `run.sh measure` computes the cost estimate with
`estimate.py` from the committed calibration receipts at the preregistered
prices, runs and allowance, and refuses when the limit you typed is not the
preregistered one, or when the estimate plus 30 percent exceeds it (FR-016).
The tasks, arms, runs per arm per task and model all come from the
preregistration's parameter block; nothing else is typed. Fetch, save and
destroy as for calibration.

## 4. Run it with Docker directly (Linux host or cloud VM)

On a Linux machine or cloud VM that holds no personal credentials and that you
delete afterwards:

```bash
git clone https://github.com/gosha70/memkernel.git && cd memkernel   # stay on the main commit to calibrate
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
2. Fetch and verify the runs (`vm.sh fetch`, which must report "copied and
   verified"), check the local copy, save the image (`vm.sh save-image`), and
   only then delete the VM
   (`vm.sh destroy`, or delete the cloud VM after copying `calibration-runs/`
   off it). If fetching fails, keep the VM until it succeeds.
3. Review `calibration-runs/<run id>/` yourself, including the secret-scan
   output, before anything from it is committed.
4. Record the configuration, cost and exclusion reasons (FR-015). The cost is
   in the Console's usage for that workspace.

#!/usr/bin/env bash
# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
#
# Run the calibration container inside a throwaway local Lima VM (README.md, "Run it in a Lima VM").
#
#   vm.sh create            create and start the VM: no shared folders, no SSH agent, Docker inside
#   vm.sh check             show that the VM sees none of your Mac's files and holds no credentials
#   vm.sh build [SHA]       clone the public repo at SHA (default: this checkout's HEAD) in the VM, build the image
#   vm.sh demo              the credential-free demonstration, in the VM
#   vm.sh preflight         ask for the key and workspace ID (hidden), check them; spends nothing
#   vm.sh calibrate         ask again, then the paid calibration run
#   vm.sh fetch [DEST]      copy the VM's runs directory to DEST on your Mac (default ./calibration-runs)
#   vm.sh destroy           stop and delete the VM and everything in it
#
# The key is read at a hidden prompt and handed to the VM on stdin. It is never written to a
# file, never put on a command line, and the host environment is never forwarded (no --preserve-env).
set -euo pipefail

vm=${CALIBRATION_VM:-mk-calibration}
repo_url=https://github.com/gosha70/memkernel.git
guest_repo=memkernel        # under the VM user's home
guest_runs=runs             # under the VM user's home, mounted at /runs in the container
docker_flags="--rm --tmpfs /tmp:rw,size=1g"

in_vm() {  # run a bash script in the VM, from the VM user's home, with nothing from the host environment
  # stdin is closed: only run_container may read the secrets that arrive on stdin
  limactl shell --workdir / "$vm" -- bash -lc "cd ~ && $1" </dev/null
}

image_tag() {
  in_vm "cat ~/.calibration-image" 2>/dev/null || {
    echo "vm.sh: no image built yet; run: vm.sh build" >&2
    exit 1
  }
}

read_secrets() {  # prints the key and the workspace ID on two lines, for the VM's stdin only
  local key workspace
  read -r -s -p "Anthropic API key (input hidden): " key </dev/tty
  echo >&2
  read -r -p "Workspace ID (wrkspc_...): " workspace </dev/tty
  [ -n "$key" ] && [ -n "$workspace" ] || { echo "vm.sh: both are required" >&2; exit 1; }
  printf '%s\n%s\n' "$key" "$workspace"
}

run_container() {  # $1 = run.sh mode; secrets arrive on stdin as two lines
  local tag
  tag=$(image_tag)
  limactl shell --workdir / "$vm" -- bash -lc "
    set -euo pipefail
    IFS= read -r ANTHROPIC_API_KEY || { echo 'vm.sh: no key arrived on stdin' >&2; exit 1; }
    IFS= read -r CALIBRATION_WORKSPACE_ID || { echo 'vm.sh: no workspace ID arrived on stdin' >&2; exit 1; }
    export ANTHROPIC_API_KEY CALIBRATION_WORKSPACE_ID
    docker run $docker_flags -e ANTHROPIC_API_KEY -e CALIBRATION_WORKSPACE_ID \
      -v \"\$HOME/$guest_runs:/runs\" '$tag' $1"
}

case "${1:-}" in
  create)
    limactl create --name "$vm" --yes \
      --cpus 4 --memory 8 --disk 40 \
      --mount-none \
      --set '.ssh.forwardAgent = false | .ssh.forwardX11 = false | .ssh.loadDotSSHPubKeys = false' \
      template:docker
    limactl start "$vm"
    # Rootless Docker maps the container's uid 1000 to a subordinate uid, so the runs directory must be
    # writable by it. The VM is disposable; the directory is world-writable only inside it.
    in_vm "mkdir -p ~/$guest_runs && chmod 1777 ~/$guest_runs && docker version --format 'docker {{.Server.Version}}'"
    echo "VM $vm is ready. Next: vm.sh check, then vm.sh build"
    ;;
  check)
    echo "== shared folders from the Mac (expect none):"
    limactl list "$vm" --format '{{range .Config.Mounts}}{{.Location}} {{end}}' | sed 's/^$/none/'
    echo "== the Mac's home directory, seen from the VM (expect: no such directory):"
    in_vm "ls -d '$HOME' 2>&1 || true"
    echo "== credential files in the VM (expect none):"
    in_vm "ls -d ~/.aws ~/.config/gcloud ~/.netrc ~/.git-credentials 2>/dev/null; \
      find ~/.ssh -type f ! -name authorized_keys ! -name known_hosts ! -name '*.pub' 2>/dev/null; true" \
      | sed '/^$/d' | grep . || echo none
    echo "== ~/.ssh/authorized_keys in the VM (expect only Lima's own login key, comment 'lima'):"
    in_vm "awk '{print \$1, \$3}' ~/.ssh/authorized_keys"
    echo "== SSH agent in the VM (expect none):"
    in_vm "echo \${SSH_AUTH_SOCK:-none}"
    echo "== environment variables in the VM whose names look like secrets (expect none):"
    in_vm "env | cut -d= -f1 | grep -iE 'key|token|secret|password|credential' || echo none"
    ;;
  build)
    sha=${2:-$(git rev-parse HEAD)}
    in_vm "set -euo pipefail
      rm -rf ~/$guest_repo
      git clone --quiet $repo_url ~/$guest_repo
      cd ~/$guest_repo && git checkout --quiet '$sha'
      eval/lifecycle-suite/calibration/build.sh
      tag=memkernel-calibration:\$(git rev-parse HEAD | cut -c1-12)
      echo \"\$tag\" > ~/.calibration-image
      echo \"image: \$tag\"
      echo \"image id: \$(docker image inspect --format '{{.Id}}' \"\$tag\")\"
      docker run --rm --entrypoint sh \"\$tag\" -c 'grep \"^#\" /opt/environment.txt'"
    ;;
  demo)
    tag=$(image_tag)
    in_vm "docker run $docker_flags '$tag' demo"
    ;;
  preflight)
    read_secrets | run_container preflight
    ;;
  calibrate)
    echo "This is the paid run, capped by the workspace's spend limit. It takes a while; keep the Mac awake."
    read -r -p "Type 'calibrate' to start: " answer </dev/tty
    [ "$answer" = calibrate ] || { echo "vm.sh: not started" >&2; exit 1; }
    read_secrets | run_container calibrate
    ;;
  fetch)
    dest=${2:-calibration-runs}
    mkdir -p "$dest"
    limactl copy -r "$vm:$guest_runs/." "$dest/"
    echo "copied the VM's runs to $dest"
    ;;
  destroy)
    limactl delete --force "$vm"
    echo "VM $vm deleted"
    ;;
  *)
    sed -n '4,17p' "$0" | sed 's/^# \{0,1\}//'
    exit 2
    ;;
esac

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
#                           and verify the copy file by file (sha256); run it after every run, failed ones too
#   vm.sh save-image [FILE] copy the built image out of the VM as a verified .tar.gz on your Mac
#                           (default ~/memkernel-calibration-image-<image id 12>.tar.gz)
#   vm.sh load-image FILE   load a saved image into this VM and check its image ID
#   vm.sh wiring            the credential-free wiki-bridge wiring check (task 18a): mounts
#                           eval/lifecycle-suite/wiring/ at this checkout's commit (refused when it has
#                           uncommitted changes) read-only into the built image, runs it there; refuses
#                           when the rest of eval/lifecycle-suite/ differs from the image's commit
#   vm.sh destroy           delete the VM; refuses while it holds runs that were not fetched and verified
#   vm.sh destroy --discard delete the VM even so, throwing those runs away
#
# The key is read at a hidden prompt and handed to the VM on stdin. It is never written to a
# file, never put on a command line, and the host environment is never forwarded (no --preserve-env).
set -euo pipefail

vm=${CALIBRATION_VM:-mk-calibration}
repo_url=https://github.com/gosha70/memkernel.git
guest_repo=memkernel        # under the VM user's home
guest_runs=runs             # under the VM user's home, mounted at /runs in the container
docker_flags="--rm --tmpfs /tmp:rw,size=1g"
fetched_manifest=.calibration-fetched   # under the VM user's home: the manifest of the last verified fetch

# Runs in the guest shell, which does not inherit this script's pipefail: any failure must fail the whole inventory.
manifest_cmd="set -euo pipefail; cd ~/$guest_runs && find . -type f -print0 | LC_ALL=C sort -z | xargs -0 -r sha256sum"
readable_cmd="sudo chmod -R a+rX ~/$guest_runs"   # rootless Docker writes the runs as a subordinate uid

vm_state() {  # prints present or absent; exits non-zero when Lima cannot say
  local names
  names=$(limactl list -q 2>/dev/null) || return 1
  if printf '%s\n' "$names" | grep -qx "$vm"; then echo present; else echo absent; fi
}

in_vm() {  # run a bash script in the VM, from the VM user's home, with nothing from the host environment
  # stdin is closed: only run_container may read the secrets that arrive on stdin
  limactl shell --workdir / "$vm" -- bash -lc "cd ~ && $1" </dev/null
}

in_vm_stdin() {  # like in_vm, but the VM command reads this script's stdin
  limactl shell --workdir / "$vm" -- bash -lc "cd ~ && $1"
}

# The selected image is kept by its immutable ID in ~/.calibration-image (tag in ~/.calibration-tag, for
# display and save-image only): loading another archive may repoint a tag, never an ID.
selected_image() {
  local value
  value=$(in_vm "cat ~/.calibration-image" 2>/dev/null) || {
    echo "vm.sh: no image selected yet; run: vm.sh build (or vm.sh load-image FILE)" >&2
    exit 1
  }
  if [[ ! "$value" =~ ^sha256:[0-9a-f]{64}$ ]]; then  # an older vm.sh stored the tag: pin it to its ID once
    local tag=$value
    value=$(in_vm "docker image inspect --format '{{.Id}}' '$tag'") || {
      echo "vm.sh: the selected tag $tag no longer resolves to an image" >&2
      exit 1
    }
    in_vm "echo '$value' > ~/.calibration-image && echo '$tag' > ~/.calibration-tag"
  fi
  printf '%s\n' "$value"
}

selected_tag() {
  in_vm "cat ~/.calibration-tag 2>/dev/null || true"
}

remove_vm_archive() {  # EXIT trap of save-image and load-image: the archive (~3 GB) never outlives the command
  in_vm "rm -f ~/calibration-image.tar.gz ~/calibration-image.sha256" \
    || echo "vm.sh: could not remove ~/calibration-image.tar.gz in the VM; remove it: limactl shell $vm rm -f calibration-image.tar.gz" >&2
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
  tag=$(selected_image)
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
      id=\$(docker image inspect --format '{{.Id}}' \"\$tag\")
      echo \"\$id\" > ~/.calibration-image
      echo \"\$tag\" > ~/.calibration-tag
      echo \"image: \$tag\"
      echo \"image id: \$id\"
      docker run --rm --entrypoint sh \"\$tag\" -c 'grep \"^#\" /opt/environment.txt'"
    ;;
  save-image)
    id=$(selected_image)
    tag=$(selected_tag)
    [ -n "$tag" ] || { echo "vm.sh: the selected image has no recorded tag" >&2; exit 1; }
    if [ "$(in_vm "docker image inspect --format '{{.Id}}' '$tag'")" != "$id" ]; then
      echo "vm.sh: the tag $tag no longer points at the selected image $id; not saving" >&2
      exit 1
    fi
    id12=$(printf '%s' "${id#sha256:}" | cut -c1-12)
    out=${2:-$HOME/memkernel-calibration-image-$id12.tar.gz}
    trap remove_vm_archive EXIT
    in_vm "set -euo pipefail; docker save '$tag' | gzip -1 > ~/calibration-image.tar.gz; sha256sum ~/calibration-image.tar.gz | cut -d' ' -f1 > ~/calibration-image.sha256"
    limactl copy "$vm:calibration-image.tar.gz" "$out"
    remote_sum=$(in_vm "cat ~/calibration-image.sha256")
    local_sum=$(shasum -a 256 "$out" | cut -d' ' -f1)
    if [ "$remote_sum" != "$local_sum" ]; then
      echo "vm.sh: the saved image does not match the VM's copy; keep the VM and retry" >&2
      exit 1
    fi
    printf '%s\n%s\n%s\n' "image: $tag" "image id: $id" "archive sha256: $local_sum" > "$out.txt"
    echo "saved $tag ($id) to $out, verified (sha256 $local_sum); details in $out.txt"
    ;;
  load-image)
    file=${2:?usage: vm.sh load-image FILE   (FILE.txt from save-image must sit next to it)}
    meta="$file.txt"
    fail() { echo "vm.sh: $1; nothing was loaded and the selected image is unchanged" >&2; exit 1; }  # before docker load
    [ -f "$file" ] || fail "no archive at $file"
    [ -f "$meta" ] || fail "no record at $meta (written by save-image)"
    tag=$(sed -n 's/^image: //p' "$meta")
    expected=$(sed -n 's/^image id: //p' "$meta")
    archive_sum=$(sed -n 's/^archive sha256: //p' "$meta")
    [[ "$tag" =~ ^memkernel-calibration:[0-9a-f]{12}$ ]] || fail "the record has no valid image tag"
    [[ "$expected" =~ ^sha256:[0-9a-f]{64}$ ]] || fail "the record has no valid image ID"
    [[ "$archive_sum" =~ ^[0-9a-f]{64}$ ]] || fail "the record has no valid archive sha256"
    [ "$(shasum -a 256 "$file" | cut -d' ' -f1)" = "$archive_sum" ] || fail "the archive does not match its recorded sha256"
    # Before anything moves: pin an existing selection to its immutable ID (an older vm.sh stored a tag, which a
    # load could repoint), and note the image the tag points at now, to put it back if the load is rejected.
    if in_vm "test -s ~/.calibration-image"; then
      selected_image > /dev/null
    fi
    previous=$(in_vm "docker image inspect --format '{{.Id}}' '$tag' 2>/dev/null || true")
    trap remove_vm_archive EXIT
    limactl copy "$file" "$vm:calibration-image.tar.gz"
    in_vm "set -euo pipefail
      [ \"\$(sha256sum ~/calibration-image.tar.gz | cut -d' ' -f1)\" = '$archive_sum' ]" \
      || fail "the copy in the VM does not match the recorded sha256"
    # From here docker load may have moved $tag: every failure restores the tag's previous image.
    after_load() {
      local moved_to cleanup="" selected=""
      moved_to=$(in_vm "docker image inspect --format '{{.Id}}' '$tag' 2>/dev/null || true")
      selected=$(in_vm "cat ~/.calibration-image 2>/dev/null || true")
      if [ -n "$previous" ]; then
        in_vm "docker tag '$previous' '$tag'" && restored="the tag $tag points at its previous image $previous again" \
          || restored="restoring the tag $tag to $previous FAILED"
      else
        restored="the tag $tag did not exist before this load"
      fi
      # The image the failed load put under the tag is removed by ID, never by tag, and never the previous or
      # selected image; no force, so docker refuses if anything still uses it.
      if [ -n "$moved_to" ] && [ "$moved_to" != "$previous" ] && [ "$moved_to" != "$selected" ]; then
        if in_vm "docker image rm '$moved_to' > /dev/null"; then
          cleanup="; removed the rejected image $moved_to"
        else
          cleanup="; could not remove the rejected image $moved_to (remove it by ID: docker image rm $moved_to)"
        fi
      fi
      echo "vm.sh: $1; the archive was loaded or partly loaded and is rejected; $restored$cleanup; the selected image (kept by ID) is unchanged; untagged layers a failed load leaves behind can be removed with: docker image prune" >&2
      exit 1
    }
    in_vm "set -euo pipefail; gunzip -c ~/calibration-image.tar.gz | docker load" || after_load "docker load failed"
    id=$(in_vm "docker image inspect --format '{{.Id}}' '$tag'") || after_load "the VM has no image $tag after loading"
    [ "$id" = "$expected" ] || after_load "the loaded image ID $id is not the recorded $expected"
    in_vm "echo '$id' > ~/.calibration-image && echo '$tag' > ~/.calibration-tag"   # select only after every check
    echo "loaded and verified $tag ($id)"
    ;;
  wiring)
    tag=$(selected_image)
    here=$(cd "$(dirname "$0")/.." && pwd)/wiring
    # The output ticks task 18a, so the check that runs must be exactly one commit's: refuse uncommitted changes,
    # and copy that commit's files (git archive), not the working tree with whatever is ignored or untracked in it.
    commit=$(git -C "$here" rev-parse HEAD) || { echo "vm.sh: $here is not in a git checkout" >&2; exit 1; }
    if [ -n "$(git -C "$here" status --porcelain -- .)" ]; then
      echo "vm.sh: $here has uncommitted changes; commit or stash them, so the check is exactly commit $commit:" >&2
      git -C "$here" status --short -- . >&2
      exit 1
    fi
    # The check runs the image's runner, arm and task code through internal functions: that code must be what
    # the check was written against. Only wiring/ (mounted from here) and calibration/ (not on the check's path,
    # the entrypoint is overridden) may differ between the image's commit and this one.
    code=$(in_vm "docker run --rm --entrypoint sh '$tag' -c 'echo \$CODE_SHA'")
    suite=$(dirname "$here")
    if ! git -C "$suite" cat-file -e "$code^{commit}" 2>/dev/null; then
      echo "vm.sh: the image's commit '$code' is not in this checkout (git fetch?); cannot compare the runner" >&2
      exit 1
    fi
    drift=$(git -C "$suite" diff --name-only "$code" HEAD -- . ':(exclude)wiring' ':(exclude)calibration')
    if [ -n "$drift" ]; then
      echo "vm.sh: eval/lifecycle-suite/ differs between the image's commit $code and $commit outside wiring/ and" \
        "calibration/; the check would not test the code it was written against:" >&2
      printf '%s\n' "$drift" >&2
      exit 1
    fi
    staged=$(mktemp -d)
    trap 'rm -rf "$staged"' EXIT
    git -C "$here" archive HEAD | tar -x -C "$staged"   # run from wiring/, git archive takes only that directory
    in_vm "rm -rf ~/wiring"
    limactl copy -r "$staged" "$vm:wiring"
    check_sha=$(shasum -a 256 "$staged/wiring_check.py" | cut -d' ' -f1)
    echo "image: $(selected_tag)"
    echo "image id: $tag"
    echo "image code: $code"
    echo "check: commit $commit (clean, copied with git archive) wiring_check.py sha256 $check_sha"
    echo "runner: eval/lifecycle-suite/ outside wiring/ and calibration/ is identical at $code and $commit"
    in_vm "docker run $docker_flags --entrypoint /opt/mk-venv/bin/python -v \$HOME/wiring:/check:ro '$tag' \
      /check/wiring_check.py --suite /opt/memkernel/eval/lifecycle-suite \
      --memkernel-cmd /opt/mk-venv/bin/memkernel --python /opt/mk-venv/bin/python --shared-cache /opt/cache"
    ;;
  demo)
    tag=$(selected_image)
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
    in_vm "$readable_cmd"   # the VM is throwaway; readable runs are needed for the copy and the inventory
    limactl copy -r "$vm:$guest_runs/." "$dest/"
    chmod 755 "$dest"   # the copy carries over the VM directory's 1777 mode
    if ! remote=$(in_vm "$manifest_cmd"); then
      echo "vm.sh: could not list the VM's runs; nothing is marked fetched. Keep the VM and retry." >&2
      exit 1
    fi
    files=0 bad=0
    while read -r sum path; do
      [ -n "$path" ] || continue
      files=$((files + 1))
      local_sum=$(shasum -a 256 "$dest/$path" 2>/dev/null | cut -d' ' -f1)
      if [ "$local_sum" != "$sum" ]; then
        if [ -z "$local_sum" ]; then echo "vm.sh: missing locally: $path" >&2; else echo "vm.sh: mismatch: $path" >&2; fi
        bad=$((bad + 1))
      fi
    done <<< "$remote"
    if [ "$bad" -ne 0 ]; then
      echo "vm.sh: $bad of $files file(s) in $dest do not match the VM; nothing is marked fetched. Keep the VM and retry." >&2
      exit 1
    fi
    printf '%s\n' "$remote" | in_vm_stdin "cat > ~/$fetched_manifest"
    echo "copied and verified $files file(s) from the VM's runs to $dest (sha256 per file)"
    ;;
  destroy)
    if ! state=$(vm_state); then
      echo "vm.sh: Lima could not list its VMs; not deleting anything. Check 'limactl list' and retry." >&2
      exit 1
    fi
    if [ "$state" = absent ]; then
      echo "vm.sh: there is no VM named $vm; nothing to delete"
      exit 0
    fi
    if [ "${2:-}" != "--discard" ]; then  # fail closed: any doubt about the runs keeps the VM
      refuse() {
        echo "vm.sh: $1; the VM is kept. Run: vm.sh fetch (then destroy). To throw the runs away: vm.sh destroy --discard" >&2
        exit 1
      }
      in_vm "$readable_cmd" || refuse "could not make the VM's runs readable (is the VM running? limactl start $vm)"
      current=$(in_vm "$manifest_cmd") || refuse "could not list the VM's runs"
      fetched=$(in_vm "cat ~/$fetched_manifest 2>/dev/null || true") || refuse "could not read the last verified fetch"
      if [ -n "$current" ] && [ "$current" != "$fetched" ]; then
        refuse "the VM holds runs that were not fetched and verified since they last changed"
      fi
    fi
    limactl delete --force "$vm"
    echo "VM $vm deleted"
    ;;
  *)
    sed -n '4,17p' "$0" | sed 's/^# \{0,1\}//'
    exit 2
    ;;
esac

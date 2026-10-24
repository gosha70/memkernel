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

# The host block (FR-015 isolation). Lima's user-mode network reaches the Mac through its gateway, and NAT reaches
# the Mac's own addresses and the rest of the LAN. The VM may send only DNS and DHCP to the gateway; every other
# private, link-local or CGNAT destination is rejected, for the VM and for the containers in it (rootless Docker's
# traffic leaves through the VM). Connections to the VM's own non-loopback addresses are rejected too, so a
# container cannot reach the VM's services (its sshd) through the network helper; loopback stays open in the VM. Inbound connections, which is how Lima's ssh, copy and port forwarding work, are
# untouched: their replies are established traffic.
host_gateway=192.168.5.2
probe_uid=65534   # nobody: the probes run as this user, so only they move the probe counter
isolation_table="inet mk_isolation"
private_ranges="10.0.0.0/8, 100.64.0.0/10, 169.254.0.0/16, 172.16.0.0/12, 192.168.0.0/16"
isolation_rules() {  # $1 = the VM user's uid: rootless Docker's network helper, so the containers' traffic, runs as it
  # Established and related traffic first: a reject answers with an ICMP error that the VM sends to its own address,
  # which the own-address rule would otherwise reject in turn, leaving the rejected connection to hang.
  cat << EOF
table $isolation_table
delete table $isolation_table
table $isolation_table {
  chain output {
    type filter hook output priority 0; policy accept;
    ct state established,related accept
    ip daddr != 127.0.0.0/8 fib daddr type local counter reject with icmp type admin-prohibited
    ip6 daddr != ::1 fib daddr type local counter reject with icmpv6 type admin-prohibited
    oifname "lo" accept
    ip daddr $host_gateway udp dport { 53, 67 } accept
    ip daddr $host_gateway tcp dport 53 accept
    meta skuid $probe_uid ip daddr { $private_ranges } counter
    meta skuid $1 ip daddr { $private_ranges } counter
    ip daddr { $private_ranges } counter reject with icmp type admin-prohibited
    ip6 daddr { fc00::/7, fe80::/10 } counter reject with icmpv6 type admin-prohibited
  }
}
EOF
}
# Probed by connecting to TCP ports on Lima's gateway, the Mac's own addresses and two LAN addresses, as user
# $probe_uid. A counting-only rule just before the reject matches that user's packets to the same addresses, so
# nothing else in the VM moves its counter, and every packet it counts goes on to the reject. A probe counts as
# blocked only if it fails with "No route to host" and that counter rose during the probe: then this rule rejected
# it. The rule matches by destination address alone, so it covers every port and protocol; the probes show it is
# loaded and effective, not each port.
probe_ports="22 80 443 8080"
probe_sh='set -uo pipefail
rejected() { sudo nft list table '"$isolation_table"' 2> /dev/null | grep "skuid '"$probe_uid"' " | grep -o "packets [0-9]*" | cut -d" " -f2; }
for address in $ADDRESSES; do
  for port in $PORTS; do
    before=$(rejected); before=${before:-0}
    out=$(sudo -u "#'"$probe_uid"'" timeout 5 bash -c "echo > /dev/tcp/$address/$port" 2>&1 | head -1)
    after=$(rejected); after=${after:-0}
    counted=$((after - before))
    case "$out" in
      *"No route to host"*) [ "$counted" -gt 0 ] && result=blocked || result="NOT BLOCKED (failed, but not by the rule)" ;;
      *) result="NOT BLOCKED (${out:-connected, or no answer within 5 s})" ;;
    esac
    echo "$address:$port $result"
  done
done'
# The agent runs in the container, so the same is probed from there: a throwaway container of the selected image,
# with the real run's flags. Its traffic leaves through rootless Docker's network helper, which runs as the VM user,
# and the helper turns the VM's rejection into "Connection refused". A probe to the Mac or the LAN counts as blocked
# only if it fails while the VM user's counting rule rose; one to the VM's own addresses only if it fails while the
# own-address reject rule rose. Addresses on Docker bridges (docker*, br-*) are probed too, but only for failing:
# inside rootless Docker the container's own namespace uses the same addresses (172.17.0.1 is its gateway there), so
# such a probe never leaves it and no VM counter can rise; whatever answers there must still refuse. 10.0.2.2 (the VM's loopback as the helper would map it) must fail too: rootless Docker's
# --disable-host-loopback stops it, not this block.
container_probe_sh='set -uo pipefail
count() { sudo nft list table '"$isolation_table"' 2> /dev/null | grep -F "$1" | grep -o "packets [0-9]*" | head -1 | cut -d" " -f2; }
probe() {  # $1 address, $2 port, $3 the counter rule to read (empty: none applies)
  local before after out
  before=0; [ -n "$3" ] && before=$(count "$3")
  out=$(docker run '"$docker_flags"' --entrypoint bash "$IMAGE" -c "timeout 5 bash -c \"echo > /dev/tcp/$1/$2\" 2>&1 | head -1" 2>&1)
  after=0; [ -n "$3" ] && after=$(count "$3")
  case "$out" in
    *"Connection refused"*|*"No route to host"*)
      if [ -z "$3" ] || [ $((${after:-0} - ${before:-0})) -gt 0 ]; then
        echo "container -> $1:$2 blocked${4:-}"
      else
        echo "container -> $1:$2 NOT BLOCKED (failed, but not by the rule)"
      fi ;;
    *) echo "container -> $1:$2 NOT BLOCKED (${out:-connected, or no answer within 5 s})" ;;
  esac
}
for target in $MAC_TARGETS; do probe "${target%:*}" "${target#*:}" "skuid $VM_UID "; done
for address in $(ip -4 -o addr show scope global | awk "\$2 !~ /^(docker|br-)/ {print \$4}" | cut -d/ -f1); do
  probe "$address" 22 "fib daddr type local"
done
for address in $(ip -4 -o addr show scope global | awk "\$2 ~ /^(docker|br-)/ {print \$4}" | cut -d/ -f1); do
  probe "$address" 22 "" " (the container'"'"'s own gateway; no VM rule involved)"
done
probe 10.0.2.2 22 "" " (by rootless Docker'"'"'s --disable-host-loopback)"'
# Loaded at every boot before the network, like Ubuntu's own nftables.service (DefaultDependencies=no avoids an
# ordering cycle with sysinit.target that would drop the network job).
isolation_unit="[Unit]
Description=Block the calibration VM from reaching the Mac and private networks
DefaultDependencies=no
Wants=network-pre.target
Before=network-pre.target shutdown.target
Conflicts=shutdown.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/sbin/nft -f /etc/mk-isolation.nft

[Install]
WantedBy=sysinit.target"

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

install_host_block() {
  local gateway
  gateway=$(in_vm "ip -4 route show default | awk '{print \$3; exit}'")
  if [ "$gateway" != "$host_gateway" ]; then
    echo "vm.sh: the VM's gateway is '$gateway', not Lima's $host_gateway; the host block would not fit" >&2
    exit 1
  fi
  isolation_rules "$(in_vm "id -u")" | in_vm_stdin "sudo tee /etc/mk-isolation.nft > /dev/null"
  printf '%s\n' "$isolation_unit" | in_vm_stdin "sudo tee /etc/systemd/system/mk-isolation.service > /dev/null"
  in_vm "set -euo pipefail; sudo systemctl daemon-reload; sudo systemctl enable --now mk-isolation.service 2> /dev/null"
  require_host_block vm-only   # no image exists yet; preflight and calibrate probe from a container too
}

verify_host_block() {  # probes as described at probe_sh; sets probe_report, returns 0 only if all held
  local addresses probes blocked
  addresses="$host_gateway $(ifconfig 2> /dev/null | awk '/inet / && $2 != "127.0.0.1" {print $2}') 192.168.1.1 10.0.0.1"
  probe_report=$(in_vm "ADDRESSES='$addresses' PORTS='$probe_ports'; $probe_sh") || return 1
  probes=$(printf '%s\n' "$probe_report" | grep -c -e ' blocked$' -e ' NOT BLOCKED') || true
  blocked=$(printf '%s\n' "$probe_report" | grep -c ' blocked$') || true
  probe_report="$probe_report
host block: $blocked of $probes probe(s) blocked by its reject rule"
  [ "$probes" -gt 0 ] && [ "$blocked" -eq "$probes" ]
}

verify_container_block() {  # as described at container_probe_sh; sets container_report, returns 0 only if all held
  local image mac targets probes blocked
  image=$(selected_image)
  mac=$(ifconfig 2> /dev/null | awk '/inet / && $2 != "127.0.0.1" {print $2}')
  targets="$host_gateway:22 $host_gateway:80"
  for address in $mac 192.168.1.1 10.0.0.1; do targets="$targets $address:80"; done
  container_report=$(in_vm "IMAGE='$image' MAC_TARGETS='$targets' VM_UID=\$(id -u); $container_probe_sh") || return 1
  probes=$(printf '%s\n' "$container_report" | grep -c '^container -> ') || true
  blocked=$(printf '%s\n' "$container_report" | grep -c '^container -> .* blocked') || true
  container_report="$container_report
host block, from a container of $image: $blocked of $probes probe(s) blocked"
  [ "$probes" -gt 0 ] && [ "$blocked" -eq "$probes" ]
}

require_host_block() {  # before the key is asked for: no paid run in a VM that can reach the Mac; $1 = vm-only at create
  local refuse="vm.sh: the VM's host block is not in place (FR-015 isolation)"
  if ! in_vm "systemctl is-enabled --quiet mk-isolation.service"; then
    echo "$refuse: its unit is not enabled; delete the VM and run vm.sh create" >&2
    exit 1
  fi
  # Reapply this script's own copy, so that an edited, flushed or deleted table is replaced, then prove it holds.
  if ! isolation_rules "$(in_vm "id -u")" \
    | in_vm_stdin "sudo tee /etc/mk-isolation.nft > /dev/null && sudo nft -f /etc/mk-isolation.nft"; then
    echo "$refuse: reapplying it failed" >&2
    exit 1
  fi
  if ! verify_host_block; then
    printf '%s\n' "$probe_report" >&2
    echo "$refuse: it did not block every probe through its own rule; do not run preflight or calibrate here" >&2
    exit 1
  fi
  printf '%s\n' "$probe_report" | tail -1
  [ "${1:-}" = vm-only ] && return 0
  if ! verify_container_block; then  # the agent runs in the container: the evidence must come from there too
    printf '%s\n' "$container_report" >&2
    echo "$refuse: a container of the selected image got past it; do not run preflight or calibrate here" >&2
    exit 1
  fi
  printf '%s\n' "$container_report" | tail -1
}

# The selected image is kept by its immutable ID in ~/.calibration-image (tag in ~/.calibration-tag, for
# display and save-image only): loading another archive may repoint a tag, never an ID.
# Guest shell: select_image ID TAG replaces each file by a rename, never rewriting one in place (an empty value
# removes it); the ID file goes last, since it alone decides what later commands run.
select_sh='select_image() ( cd ~ && for kv in ".calibration-tag=$2" ".calibration-image=$1"; do
  f=${kv%%=*}; v=${kv#*=}
  if [ -n "$v" ]; then printf "%s\n" "$v" > "$f.new" && mv -f "$f.new" "$f" || exit 1; else rm -f "$f" || exit 1; fi
done )'
set_selection() {  # $1 image ID, $2 tag
  in_vm "$select_sh; select_image '$1' '$2'"
}

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
    set_selection "$value" "$tag" || { echo "vm.sh: could not pin the selected tag $tag to $value" >&2; exit 1; }
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
    install_host_block
    echo "VM $vm is ready, with the host block in place. Next: vm.sh check, then vm.sh build"
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
    failures=0
    echo "== the host block: TCP probes to the Mac and LAN addresses (expect: blocked, all counted by its rule):"
    verify_host_block || failures=$((failures + 1))
    printf '%s\n' "$probe_report"
    echo "   (the rule matches by destination address, with no port: these probes show it loaded and effective)"
    echo "== the host block, from a container of the selected image with the run's flags (expect: blocked):"
    if in_vm "test -s ~/.calibration-image"; then
      verify_container_block || failures=$((failures + 1))
      printf '%s\n' "$container_report"
    else
      echo "no image selected yet: run vm.sh check again after vm.sh build"
    fi
    echo "== DNS and the Anthropic API, seen from the VM (expect: an address, then HTTP 401):"
    egress=$(in_vm "getent hosts api.anthropic.com | head -1
      curl -s -o /dev/null -w 'HTTP %{http_code}\n' --connect-timeout 10 https://api.anthropic.com/v1/models || true")
    printf '%s\n' "$egress"
    case "$egress" in *"HTTP 401"*) ;; *) failures=$((failures + 1)) ;; esac
    echo "== Lima's channels: copy both ways and port forwarding (expect: ok):"
    probe_file=$(mktemp)
    echo "vm.sh check $$" > "$probe_file"
    if limactl copy "$probe_file" "$vm:.vm-check-probe" && limactl copy "$vm:.vm-check-probe" "$probe_file.back" \
      && cmp -s "$probe_file" "$probe_file.back"; then echo "copy: ok"; else echo "copy: FAILED"; failures=$((failures + 1)); fi
    rm -f "$probe_file" "$probe_file.back"
    # A port the Mac's OS reports free and a one-off answer, so nothing else listening can pass for the VM.
    port=$(python3 -c 'import socket; s = socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1])')
    token="vm.sh check $$ $RANDOM"
    in_vm "rm -f ~/.vm-check-probe; mkdir -p ~/.vm-check-www && echo '$token' > ~/.vm-check-www/index.html
      cd ~/.vm-check-www && setsid -f python3 -m http.server $port < /dev/null > /dev/null 2>&1"
    forwarded=""
    for _ in $(seq 1 15); do
      forwarded=$(curl -s --connect-timeout 2 "http://127.0.0.1:$port/index.html" || true)
      [ "$forwarded" = "$token" ] && break
      sleep 1
    done
    in_vm "pkill -f 'http[.]server $port' || true; rm -rf ~/.vm-check-www"   # [.]: not this shell's own line
    if [ "$forwarded" = "$token" ]; then echo "port forwarding: ok"; else echo "port forwarding: FAILED"; failures=$((failures + 1)); fi
    if [ "$failures" -gt 0 ]; then
      echo "vm.sh check: $failures isolation check(s) failed; do not run preflight or calibrate in this VM" >&2
      exit 1
    fi
    echo "vm.sh check: every host-block probe failed as its line requires, and Lima's channels work"
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
      $select_sh
      select_image \"\$id\" \"\$tag\"
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
    previous_selection=$(in_vm "cat ~/.calibration-image 2>/dev/null || true")
    previous_selection_tag=$(in_vm "cat ~/.calibration-tag 2>/dev/null || true")
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
      echo "vm.sh: $1; the archive was loaded or partly loaded and is rejected; $restored$cleanup; the selected image is ${selected:-none}; untagged layers a failed load leaves behind can be removed with: docker image prune" >&2
      exit 1
    }
    in_vm "set -euo pipefail; gunzip -c ~/calibration-image.tar.gz | docker load" || after_load "docker load failed"
    id=$(in_vm "docker image inspect --format '{{.Id}}' '$tag'") || after_load "the VM has no image $tag after loading"
    [ "$id" = "$expected" ] || after_load "the loaded image ID $id is not the recorded $expected"
    if ! set_selection "$id" "$tag"; then   # select only after every check; a failure here rolls back too
      if set_selection "$previous_selection" "$previous_selection_tag"; then
        selection="the previous selection is restored"
      else
        selection="restoring the previous selection FAILED; check ~/.calibration-image and ~/.calibration-tag in the VM"
      fi
      after_load "could not record $id as the selection ($selection)"
    fi
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
    chmod 755 "$staged"   # mktemp makes it 0700; the container runs as uid 1000, not as the VM user it maps to
    git -C "$here" archive HEAD | tar -x -C "$staged"   # run from wiring/, git archive takes only that directory
    in_vm "rm -rf ~/wiring"
    limactl copy -r "$staged" "$vm:wiring"
    in_vm "chmod -R a+rX ~/wiring"   # readable by the container user, whatever modes the copy kept
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
    require_host_block
    read_secrets | run_container preflight
    ;;
  calibrate)
    require_host_block
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
      # A VM whose create stopped before the runs directory existed has nothing to lose; any other answer, or none
      # (an unreachable VM), keeps the guard below.
      runs_dir=$(in_vm "if [ -e ~/$guest_runs ]; then echo present; else echo absent; fi") \
        || refuse "could not reach the VM to look for runs (is the VM running? limactl start $vm)"
      if [ "$runs_dir" != absent ]; then
        [ "$runs_dir" = present ] || refuse "could not tell whether the VM holds runs"
        in_vm "$readable_cmd" || refuse "could not make the VM's runs readable (is the VM running? limactl start $vm)"
        current=$(in_vm "$manifest_cmd") || refuse "could not list the VM's runs"
        fetched=$(in_vm "cat ~/$fetched_manifest 2>/dev/null || true") || refuse "could not read the last verified fetch"
        if [ -n "$current" ] && [ "$current" != "$fetched" ]; then
          refuse "the VM holds runs that were not fetched and verified since they last changed"
        fi
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

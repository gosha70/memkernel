# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""vm.sh's fetch and destroy guard (eval/lifecycle-suite/calibration/vm.sh), with a stub Lima.

The stub ``limactl`` runs each guest command with bash in a fake guest home on
the local disk, copies from that home, and records a deletion instead of
deleting anything, so the guard is tested exactly as written and no Lima is
needed. The guard must fail closed: any doubt about the runs keeps the VM.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.unit._lifecycle_suite import SUITE_DIR

pytestmark = [
    pytest.mark.unit,
    pytest.mark.skipif(shutil.which("bash") is None, reason="vm.sh is a bash script"),
]

VM_SH = SUITE_DIR / "calibration" / "vm.sh"

STUB_LIMACTL = r"""#!/bin/bash
echo "$*" >> "$STUB_LOG"
case "$1" in
  list)
    [ "${STUB_LIST_EXIT:-0}" = 0 ] || exit "$STUB_LIST_EXIT"
    [ -n "${STUB_VMS:-}" ] && printf '%s\n' $STUB_VMS
    exit 0 ;;
  shell)
    [ -z "${STUB_SHELL_EXIT:-}" ] || exit "$STUB_SHELL_EXIT"
    cmd="${@: -1}"
    HOME="$STUB_GUEST_HOME" PATH="$STUB_GUEST_PATH" exec bash -c "$cmd" ;;
  copy)
    shift; [ "$1" = -r ] && shift
    src="${1#*:}"; dest="$2"
    cp -R "$STUB_GUEST_HOME/$src" "$dest" || exit $?
    if [ -n "${STUB_CORRUPT:-}" ]; then
      f=$(find "$dest" -name receipts.jsonl | head -1); [ -n "$f" ] && echo corrupted >> "$f"
    fi
    exit 0 ;;
  delete)
    touch "$STUB_DELETED"; exit 0 ;;
esac
echo "stub limactl: unexpected $*" >&2; exit 99
"""


def _env(tmp_path: Path, *, sudo: str = "run") -> dict[str, str]:
    host_bin, guest_bin, guest_home = tmp_path / "host-bin", tmp_path / "guest-bin", tmp_path / "guest-home"
    for directory in (host_bin, guest_bin, guest_home / "runs"):
        directory.mkdir(parents=True)
    (host_bin / "limactl").write_text(STUB_LIMACTL, encoding="utf-8")
    (host_bin / "limactl").chmod(0o755)
    # sudo in the guest: "run" executes the command, "noop" pretends to (a chmod that changes nothing)
    sudo_body = 'exec "$@"\n' if sudo == "run" else "exit 0\n"
    (guest_bin / "sudo").write_text("#!/bin/sh\n" + sudo_body, encoding="utf-8")
    (guest_bin / "sudo").chmod(0o755)
    system = "/usr/bin:/bin:/usr/sbin:/sbin"
    return {
        "PATH": f"{host_bin}{os.pathsep}{system}",
        "STUB_GUEST_PATH": f"{guest_bin}{os.pathsep}{system}",
        "STUB_GUEST_HOME": str(guest_home),
        "STUB_LOG": str(tmp_path / "limactl.log"),
        "STUB_DELETED": str(tmp_path / "DELETED"),
        "STUB_VMS": "mk-calibration",
    }


def _run(env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["bash", str(VM_SH), *args], env=env, capture_output=True, text=True, timeout=60, check=False)


def _write_run(env: dict[str, str]) -> Path:
    run = Path(env["STUB_GUEST_HOME"]) / "runs" / "calibration-x"
    (run / "c1" / "s0").mkdir(parents=True)
    (run / "receipts.jsonl").write_text("{}\n", encoding="utf-8")
    (run / "c1" / "s0" / "stream.jsonl").write_text("{}\n", encoding="utf-8")
    (run / "name with space.txt").write_text("x\n", encoding="utf-8")
    return run


def _deleted(env: dict[str, str]) -> bool:
    return Path(env["STUB_DELETED"]).exists()


def test_destroy_refuses_runs_that_were_never_fetched(tmp_path: Path) -> None:
    env = _env(tmp_path)
    _write_run(env)
    result = _run(env, "destroy")
    assert result.returncode == 1 and not _deleted(env)
    assert "not fetched and verified" in result.stderr


def test_a_verified_fetch_allows_destroy_until_the_runs_change(tmp_path: Path) -> None:
    env = _env(tmp_path)
    run = _write_run(env)
    dest = tmp_path / "fetched"
    fetched = _run(env, "fetch", str(dest))
    assert fetched.returncode == 0 and "copied and verified 3 file(s)" in fetched.stdout
    assert (dest / "calibration-x" / "name with space.txt").read_text(encoding="utf-8") == "x\n"
    assert oct(dest.stat().st_mode & 0o777) == "0o755"

    (run / "late.txt").write_text("written after the fetch\n", encoding="utf-8")
    assert _run(env, "destroy").returncode == 1 and not _deleted(env)
    assert _run(env, "fetch", str(dest)).returncode == 0
    assert _run(env, "destroy").returncode == 0 and _deleted(env)


def test_a_corrupted_copy_is_not_marked_fetched_and_keeps_the_vm(tmp_path: Path) -> None:
    env = _env(tmp_path)
    _write_run(env)
    result = _run({**env, "STUB_CORRUPT": "1"}, "fetch", str(tmp_path / "fetched"))
    assert result.returncode == 1 and "mismatch: ./calibration-x/receipts.jsonl" in result.stderr
    assert not (Path(env["STUB_GUEST_HOME"]) / ".calibration-fetched").exists()
    assert _run(env, "destroy").returncode == 1 and not _deleted(env)


def test_an_inventory_that_fails_part_way_keeps_the_vm(tmp_path: Path) -> None:
    """Review of #34: without pipefail in the guest, find's error left an empty manifest and destroy proceeded."""
    env = _env(tmp_path, sudo="noop")  # the chmod does not fix the unreadable directory
    run = _write_run(env)
    (run / "c1").chmod(0o000)
    try:
        if os.access(run / "c1", os.R_OK):
            pytest.skip("running as a user that ignores directory permissions (root)")
        result = _run(env, "destroy")
    finally:
        (run / "c1").chmod(0o755)
    assert result.returncode == 1 and not _deleted(env)
    assert "could not list the VM's runs" in result.stderr


def test_a_guest_that_cannot_be_reached_keeps_the_vm(tmp_path: Path) -> None:
    env = _env(tmp_path)
    _write_run(env)
    result = _run({**env, "STUB_SHELL_EXIT": "1"}, "destroy")  # e.g. the VM is stopped
    assert result.returncode == 1 and not _deleted(env)


def test_a_failed_vm_listing_is_not_mistaken_for_no_vm(tmp_path: Path) -> None:
    env = _env(tmp_path)
    _write_run(env)
    result = _run({**env, "STUB_LIST_EXIT": "1"}, "destroy")
    assert result.returncode == 1 and not _deleted(env)
    assert "could not list its VMs" in result.stderr
    absent = _run({**env, "STUB_VMS": "some-other-vm"}, "destroy")
    assert absent.returncode == 0 and "nothing to delete" in absent.stdout and not _deleted(env)


def test_an_empty_runs_directory_may_be_destroyed_and_discard_overrides(tmp_path: Path) -> None:
    env = _env(tmp_path)
    assert _run(env, "destroy").returncode == 0 and _deleted(env)
    Path(env["STUB_DELETED"]).unlink()
    _write_run(env)
    result = _run(env, "destroy", "--discard")
    assert result.returncode == 0 and _deleted(env)

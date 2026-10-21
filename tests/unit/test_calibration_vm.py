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
from typing import Any

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
    if [ "${2#*:}" != "$2" ]; then  # host -> guest
      cp -R "$1" "$STUB_GUEST_HOME/${2#*:}" || exit $?
      exit 0
    fi
    src="${1#*:}"; dest="$2"
    cp -R "$STUB_GUEST_HOME/$src" "$dest" || exit $?
    if [ -n "${STUB_CORRUPT:-}" ]; then
      f=$(find "$dest" -name receipts.jsonl | head -1); [ -n "$f" ] && echo corrupted >> "$f"
    fi
    exit 0 ;;
  delete)
    touch "$STUB_DELETED"; exit 0 ;;
  create|start)
    exit 0 ;;
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
    # docker in the guest, with tags: STUB_TAGS holds "tag id" lines; "load" points STUB_LOAD_TAG at STUB_LOAD_ID
    (guest_bin / "docker").write_text(
        "#!/bin/bash\n"
        'tags="$STUB_TAGS"; touch "$tags"\n'
        'lookup() { if [[ "$1" == sha256:* ]]; then grep -q " $1$" "$tags" && echo "$1"; '
        'else awk -v t="$1" \'$1 == t {print $2}\' "$tags" | tail -1; fi; }\n'
        # moving a tag keeps the old image, as real docker does (dangling, still addressable by ID)
        'set_tag() { grep "^$1 " "$tags" | sed "s/^[^ ]* /@old /" > "$tags.new"; '
        'grep -v "^$1 " "$tags" >> "$tags.new"; echo "$1 $2" >> "$tags.new"; mv "$tags.new" "$tags"; }\n'
        'case "$1" in\n'
        # load moves the tag, then exits with STUB_LOAD_EXIT (a load that fails part-way)
        '  load) cat > /dev/null; echo load >> "$STUB_DOCKER_LOG"; set_tag "$STUB_LOAD_TAG" "$STUB_LOAD_ID"; '
        'exit "${STUB_LOAD_EXIT:-0}";;\n'
        '  tag) id=$(lookup "$2"); [ -n "$id" ] || exit 1; '
        'echo "tag $2 $3" >> "$STUB_DOCKER_LOG"; set_tag "$3" "$id";;\n'
        '  image) if [ "$2" = rm ]; then grep -v " $3$" "$tags" > "$tags.new"; mv "$tags.new" "$tags"; '
        'echo "rm $3" >> "$STUB_DOCKER_LOG"; exit 0; fi; '
        'id=$(lookup "${@: -1}"); [ -n "$id" ] || exit 1; echo "$id";;\n'
        '  save) echo "save $2" >> "$STUB_DOCKER_LOG"; echo "image bytes of $2";;\n'
        '  run) echo "run $*" >> "$STUB_DOCKER_LOG"; '
        'if [[ "$*" == *CODE_SHA* ]]; then echo "${STUB_CODE_SHA:-unknown}"; else echo "stub run"; fi;;\n'
        "  version) echo 'docker 29.9.1';;\n"
        "  *) exit 98;;\n"
        "esac\n",
        encoding="utf-8",
    )
    (guest_bin / "docker").chmod(0o755)
    system = "/usr/bin:/bin:/usr/sbin:/sbin"
    return {
        "PATH": f"{host_bin}{os.pathsep}{system}",
        "STUB_GUEST_PATH": f"{guest_bin}{os.pathsep}{system}",
        "STUB_GUEST_HOME": str(guest_home),
        "STUB_LOG": str(tmp_path / "limactl.log"),
        "STUB_DELETED": str(tmp_path / "DELETED"),
        "STUB_DOCKER_LOG": str(tmp_path / "docker.log"),
        "STUB_TAGS": str(tmp_path / "docker-tags"),
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


TAG = "memkernel-calibration:12a3ff3b60e3"
IMAGE_ID = "sha256:" + "ba4dc322" * 8  # the image the archive carries
OTHER_ID = "sha256:" + "f97e82e2" * 8  # another build of the same commit: same tag, different ID


def _saved_image(tmp_path: Path, **record: str | None) -> Path:
    """A gzip archive and its save-image record; pass a field as None to leave it out."""
    import gzip
    import hashlib

    archive = tmp_path / "image.tar.gz"
    archive.write_bytes(gzip.compress(b"not a real image, the stub docker only drains it"))
    fields = {"image": TAG, "image id": IMAGE_ID, "archive sha256": hashlib.sha256(archive.read_bytes()).hexdigest()}
    fields.update(record)
    lines = [f"{key}: {value}" for key, value in fields.items() if value is not None]
    (tmp_path / "image.tar.gz.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return archive


def _load_env(tmp_path: Path, loads_as: str = IMAGE_ID, selected: str | None = None) -> dict[str, str]:
    """The archive loads as ``loads_as`` under TAG; ``selected`` is an image already selected under TAG."""
    env = {**_env(tmp_path), "STUB_LOAD_TAG": TAG, "STUB_LOAD_ID": loads_as}
    if selected is not None:
        Path(env["STUB_TAGS"]).write_text(f"{TAG} {selected}\n", encoding="utf-8")
        home = Path(env["STUB_GUEST_HOME"])
        (home / ".calibration-image").write_text(selected + "\n", encoding="utf-8")
        (home / ".calibration-tag").write_text(TAG + "\n", encoding="utf-8")
    return env


def _selected(env: dict[str, str]) -> str:
    path = Path(env["STUB_GUEST_HOME"]) / ".calibration-image"
    return path.read_text(encoding="utf-8").strip() if path.exists() else ""


def _tag_points_at(env: dict[str, str]) -> str:
    lines = Path(env["STUB_TAGS"]).read_text(encoding="utf-8").splitlines()
    return next((line.split()[1] for line in lines if line.split()[0] == TAG), "")


def _loaded(env: dict[str, str]) -> bool:
    log = Path(env["STUB_DOCKER_LOG"])
    return log.exists() and "load" in log.read_text(encoding="utf-8").split()


def test_load_image_verifies_and_selects_by_image_id(tmp_path: Path) -> None:
    env = _load_env(tmp_path)
    archive = _saved_image(tmp_path)
    result = _run(env, "load-image", str(archive))
    assert result.returncode == 0, result.stderr
    assert _loaded(env) and _selected(env) == IMAGE_ID  # the immutable ID, not the tag


@pytest.mark.parametrize(
    ("record", "message"),
    [
        ({"image": None}, "no valid image tag"),
        ({"image id": None}, "no valid image ID"),
        ({"archive sha256": None}, "no valid archive sha256"),
        ({"image id": "sha256:short"}, "no valid image ID"),
        ({"archive sha256": "0" * 64}, "does not match its recorded sha256"),
    ],
)
def test_load_image_refuses_an_incomplete_or_wrong_record_before_loading(
    tmp_path: Path, record: dict[str, str | None], message: str
) -> None:
    env = _load_env(tmp_path, selected=OTHER_ID)
    archive = _saved_image(tmp_path, **record)
    result = _run(env, "load-image", str(archive))
    assert result.returncode == 1 and message in result.stderr and "nothing was loaded" in result.stderr
    assert not _loaded(env) and _selected(env) == OTHER_ID and _tag_points_at(env) == OTHER_ID


def test_load_image_refuses_a_missing_record(tmp_path: Path) -> None:
    """Review of #35: a missing sidecar used to skip every check and exit 0."""
    env = _load_env(tmp_path)
    archive = _saved_image(tmp_path)
    (tmp_path / "image.tar.gz.txt").unlink()
    result = _run(env, "load-image", str(archive))
    assert result.returncode == 1 and "no record" in result.stderr and not _loaded(env)


def test_a_rejected_load_that_moved_the_selected_tag_puts_it_back(tmp_path: Path) -> None:
    """Review of #35: the selected image and the archive share a tag but not an ID. docker load moves the
    tag; the ID check rejects the archive; the selection (by ID) and the tag must both end where they began."""
    env = _load_env(tmp_path, loads_as=OTHER_ID, selected=IMAGE_ID)
    archive = _saved_image(tmp_path)  # records IMAGE_ID, but the archive actually carries OTHER_ID
    result = _run(env, "load-image", str(archive))
    assert result.returncode == 1 and "is not the recorded" in result.stderr
    assert "loaded or partly loaded and is rejected" in result.stderr and "nothing was loaded" not in result.stderr
    assert _loaded(env)
    assert _selected(env) == IMAGE_ID and _tag_points_at(env) == IMAGE_ID  # nothing ends up pointing elsewhere


def test_runs_use_the_selected_id_even_if_the_tag_moves(tmp_path: Path) -> None:
    env = _load_env(tmp_path, selected=IMAGE_ID)
    Path(env["STUB_TAGS"]).write_text(f"{TAG} {OTHER_ID}\n{TAG}-old {IMAGE_ID}\n", encoding="utf-8")
    result = _run(env, "save-image", str(tmp_path / "out.tar.gz"))  # the tag no longer points at the selection
    assert result.returncode == 1 and "no longer points at the selected image" in result.stderr


def test_load_image_refuses_a_copy_that_differs_inside_the_vm(tmp_path: Path) -> None:
    env = _load_env(tmp_path, selected=OTHER_ID)
    archive = _saved_image(tmp_path)
    stub = Path(env["PATH"].split(os.pathsep)[0]) / "limactl"
    stub.write_text(  # the host -> guest copy arrives altered
        stub.read_text(encoding="utf-8").replace(
            'cp -R "$1" "$STUB_GUEST_HOME/${2#*:}" || exit $?',
            'cp -R "$1" "$STUB_GUEST_HOME/${2#*:}" || exit $?; echo x >> "$STUB_GUEST_HOME/${2#*:}"',
        ),
        encoding="utf-8",
    )
    result = _run(env, "load-image", str(archive))
    assert result.returncode == 1 and not _loaded(env)
    assert _selected(env) == OTHER_ID and _tag_points_at(env) == OTHER_ID


def test_an_older_tag_selection_is_pinned_to_its_id_once(tmp_path: Path) -> None:
    env = _load_env(tmp_path)
    Path(env["STUB_TAGS"]).write_text(f"{TAG} {IMAGE_ID}\n", encoding="utf-8")
    (Path(env["STUB_GUEST_HOME"]) / ".calibration-image").write_text(TAG + "\n", encoding="utf-8")  # old format
    _run(env, "save-image", str(tmp_path / "pinned.tar.gz"))  # the stub has no docker save; pinning is the test
    assert _selected(env) == IMAGE_ID  # resolved and stored by ID before anything else


@pytest.mark.parametrize("legacy", [False, True], ids=["selected-by-id", "legacy-tag-selection"])
def test_a_load_that_moves_the_shared_tag_and_then_fails_keeps_the_original_selection(
    tmp_path: Path, legacy: bool
) -> None:
    """Review of #35: docker load repoints the shared tag, then exits 17. The selection must stay the original
    image (a legacy tag-format selection is pinned to its ID before loading) and the tag must point back at it."""
    env = {**_load_env(tmp_path, loads_as=OTHER_ID, selected=IMAGE_ID), "STUB_LOAD_EXIT": "17"}
    if legacy:
        (Path(env["STUB_GUEST_HOME"]) / ".calibration-image").write_text(TAG + "\n", encoding="utf-8")
        (Path(env["STUB_GUEST_HOME"]) / ".calibration-tag").unlink()
    archive = _saved_image(tmp_path)
    result = _run(env, "load-image", str(archive))
    assert result.returncode == 1 and "docker load failed" in result.stderr
    assert "loaded or partly loaded and is rejected" in result.stderr
    assert _loaded(env)
    assert _selected(env) == IMAGE_ID  # by ID, also for the legacy selection, which still names the moved tag
    assert _tag_points_at(env) == IMAGE_ID  # the shared tag was put back


def _removed(env: dict[str, str]) -> list[str]:
    log = Path(env["STUB_DOCKER_LOG"])
    lines = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
    return [line.split()[1] for line in lines if line.startswith("rm ")]


def test_a_successful_load_moves_the_selection_to_the_new_id(tmp_path: Path) -> None:
    env = _load_env(tmp_path, loads_as=IMAGE_ID, selected=OTHER_ID)  # another image is selected before
    archive = _saved_image(tmp_path)
    result = _run(env, "load-image", str(archive))
    assert result.returncode == 0, result.stderr
    assert _selected(env) == IMAGE_ID and _tag_points_at(env) == IMAGE_ID and _removed(env) == []


def test_a_rejected_load_removes_the_image_it_put_under_the_tag_by_id(tmp_path: Path) -> None:
    env = _load_env(tmp_path, loads_as=OTHER_ID, selected=IMAGE_ID)
    archive = _saved_image(tmp_path)  # records IMAGE_ID; the archive carries OTHER_ID
    result = _run(env, "load-image", str(archive))
    assert result.returncode == 1 and f"removed the rejected image {OTHER_ID}" in result.stderr
    assert _removed(env) == [OTHER_ID]  # by ID, not by tag
    assert _selected(env) == IMAGE_ID and _tag_points_at(env) == IMAGE_ID


def test_a_rejected_load_never_removes_the_selected_or_previous_image(tmp_path: Path) -> None:
    env = {**_load_env(tmp_path, loads_as=IMAGE_ID, selected=IMAGE_ID), "STUB_LOAD_EXIT": "17"}
    archive = _saved_image(tmp_path)  # the failed load put the already-selected image under the tag
    result = _run(env, "load-image", str(archive))
    assert result.returncode == 1 and _removed(env) == []
    assert _selected(env) == IMAGE_ID


def _vm_archive(env: dict[str, str]) -> bool:
    home = Path(env["STUB_GUEST_HOME"])
    return (home / "calibration-image.tar.gz").exists() or (home / "calibration-image.sha256").exists()


def test_save_image_verifies_the_copy_and_removes_the_archive_from_the_vm(tmp_path: Path) -> None:
    """Review of #36: the VM's disk is small; the ~3 GB archive must not stay in it."""
    env = _load_env(tmp_path, selected=IMAGE_ID)
    out = tmp_path / "saved.tar.gz"
    result = _run(env, "save-image", str(out))
    assert result.returncode == 0, result.stderr
    assert "verified" in result.stdout and out.exists() and f"image id: {IMAGE_ID}" in Path(f"{out}.txt").read_text()
    assert not _vm_archive(env)


def test_load_image_removes_the_archive_from_the_vm_whether_it_loads_or_not(tmp_path: Path) -> None:
    accepted = _load_env(tmp_path / "a")
    assert _run(accepted, "load-image", str(_saved_image(tmp_path / "a"))).returncode == 0
    rejected = _load_env(tmp_path / "r", loads_as=OTHER_ID, selected=IMAGE_ID)
    assert _run(rejected, "load-image", str(_saved_image(tmp_path / "r"))).returncode == 1
    assert not _vm_archive(accepted) and not _vm_archive(rejected)


def _git(repo: Path) -> list[str]:
    return ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.invalid"]


def _commit(repo: Path) -> str:
    subprocess.run([*_git(repo), "add", "-A"], check=True)
    subprocess.run([*_git(repo), "commit", "-q", "-m", "change"], check=True)
    return _head(repo)


def _wiring_checkout(tmp_path: Path) -> Path:
    """A suite checkout holding runner.py, vm.sh and a committed wiring/ directory, plus an ignored file in it."""
    repo = tmp_path / "repo"
    (repo / "calibration").mkdir(parents=True)
    (repo / "wiring" / "fixture").mkdir(parents=True)
    shutil.copy(VM_SH, repo / "calibration" / "vm.sh")
    (repo / "wiring" / "wiring_check.py").write_text("print('check')\n", encoding="utf-8")
    (repo / "wiring" / "fixture" / "task.json").write_text("{}\n", encoding="utf-8")
    (repo / "runner.py").write_text("RUNNER = 1\n", encoding="utf-8")
    (repo / ".gitignore").write_text(".DS_Store\n", encoding="utf-8")
    subprocess.run([*_git(repo), "init", "-q"], check=True)
    _commit(repo)
    (repo / "wiring" / "fixture" / ".DS_Store").write_text("ignored, must not be copied\n", encoding="utf-8")
    return repo


def _head(repo: Path) -> str:
    return subprocess.run([*_git(repo), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()


def _run_wiring(env: dict[str, str], repo: Path, image_commit: str | None = None) -> subprocess.CompletedProcess[str]:
    """``image_commit`` is the CODE_SHA the stub image reports; by default the checkout's HEAD."""
    return subprocess.run(
        ["bash", str(repo / "calibration" / "vm.sh"), "wiring"],
        env={**env, "HOME": str(repo.parent), "STUB_CODE_SHA": image_commit or _head(repo)},
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


@pytest.mark.skipif(shutil.which("git") is None, reason="wiring copies a git commit")
def test_wiring_runs_exactly_the_committed_check_and_names_its_commit(tmp_path: Path) -> None:
    env = _load_env(tmp_path, selected=IMAGE_ID)
    repo = _wiring_checkout(tmp_path)
    commit = _head(repo)
    result = _run_wiring(env, repo)
    assert result.returncode == 0, result.stderr
    assert f"check: commit {commit} (clean" in result.stdout
    copied = Path(env["STUB_GUEST_HOME"]) / "wiring"
    assert sorted(p.relative_to(copied).as_posix() for p in copied.rglob("*") if p.is_file()) == [
        "fixture/task.json",
        "wiring_check.py",
    ]
    assert f"/check:ro {IMAGE_ID}" in Path(env["STUB_DOCKER_LOG"]).read_text(encoding="utf-8")


@pytest.mark.skipif(shutil.which("git") is None, reason="wiring copies a git commit")
@pytest.mark.parametrize("change", ["edit", "untracked"])
def test_wiring_refuses_uncommitted_changes_to_the_check(tmp_path: Path, change: str) -> None:
    """Review of #36: the output ticks task 18a, so it must not name a commit the check does not match."""
    env = _load_env(tmp_path, selected=IMAGE_ID)
    repo = _wiring_checkout(tmp_path)
    if change == "edit":
        (repo / "wiring" / "wiring_check.py").write_text("print('edited')\n", encoding="utf-8")
    else:
        (repo / "wiring" / "fixture" / "extra.md").write_text("new\n", encoding="utf-8")
    result = _run_wiring(env, repo)
    assert result.returncode == 1 and "uncommitted changes" in result.stderr
    assert not _check_ran(env)


def _check_ran(env: dict[str, str]) -> bool:
    log = Path(env["STUB_DOCKER_LOG"])
    copied = (Path(env["STUB_GUEST_HOME"]) / "wiring").exists()
    return copied or (log.exists() and "/check:ro" in log.read_text(encoding="utf-8"))


@pytest.mark.skipif(shutil.which("git") is None, reason="wiring copies a git commit")
def test_wiring_runs_when_only_wiring_and_calibration_changed_since_the_image(tmp_path: Path) -> None:
    """The real case: the image predates the check, and vm.sh changed with it; the runner did not."""
    env = _load_env(tmp_path, selected=IMAGE_ID)
    repo = _wiring_checkout(tmp_path)
    image_commit = _head(repo)
    (repo / "wiring" / "wiring_check.py").write_text("print('newer check')\n", encoding="utf-8")
    (repo / "calibration" / "notes.md").write_text("vm.sh changed too\n", encoding="utf-8")
    _commit(repo)
    result = _run_wiring(env, repo, image_commit)
    assert result.returncode == 0, result.stderr
    assert f"image code: {image_commit}" in result.stdout and "is identical at" in result.stdout and _check_ran(env)


@pytest.mark.skipif(shutil.which("git") is None, reason="wiring copies a git commit")
def test_wiring_refuses_when_the_runner_differs_from_the_image(tmp_path: Path) -> None:
    """Review of #36: the check calls the image's runner internals; a newer check on an older runner is refused."""
    env = _load_env(tmp_path, selected=IMAGE_ID)
    repo = _wiring_checkout(tmp_path)
    image_commit = _head(repo)
    (repo / "runner.py").write_text("RUNNER = 2\n", encoding="utf-8")
    _commit(repo)
    result = _run_wiring(env, repo, image_commit)
    assert result.returncode == 1 and "differs between the image's commit" in result.stderr
    assert "runner.py" in result.stderr and not _check_ran(env)


@pytest.mark.skipif(shutil.which("git") is None, reason="wiring copies a git commit")
def test_wiring_refuses_an_image_commit_this_checkout_does_not_have(tmp_path: Path) -> None:
    env = _load_env(tmp_path, selected=IMAGE_ID)
    repo = _wiring_checkout(tmp_path)
    result = _run_wiring(env, repo, "0" * 40)
    assert result.returncode == 1 and "is not in this checkout" in result.stderr and not _check_ran(env)


@pytest.mark.skipif(shutil.which("git") is None, reason="wiring copies a git commit")
def test_wiring_leaves_the_check_readable_by_a_container_user_other_than_the_owner(tmp_path: Path) -> None:
    """Review of #36: mktemp -d is 0700, and the image runs as uid 1000, not the VM user rootless Docker maps."""
    env = _load_env(tmp_path, selected=IMAGE_ID)
    result = _run_wiring(env, _wiring_checkout(tmp_path))
    assert result.returncode == 0, result.stderr
    copied = Path(env["STUB_GUEST_HOME"]) / "wiring"
    for path in [copied, *copied.rglob("*")]:
        need = 0o005 if path.is_dir() else 0o004  # others: read, and traverse for directories
        assert path.stat().st_mode & need == need, f"{path.relative_to(copied)} is {oct(path.stat().st_mode)}"


def _selection(env: dict[str, str]) -> tuple[str, str]:
    home = Path(env["STUB_GUEST_HOME"])
    tag = home / ".calibration-tag"
    return _selected(env), tag.read_text(encoding="utf-8").strip() if tag.exists() else ""


def test_a_read_only_selection_file_does_not_split_the_selection(tmp_path: Path) -> None:
    """Review of #36: the ID file used to be rewritten first, then a read-only tag file failed the write."""
    env = _load_env(tmp_path, loads_as=IMAGE_ID, selected=OTHER_ID)
    (Path(env["STUB_GUEST_HOME"]) / ".calibration-tag").chmod(0o444)
    result = _run(env, "load-image", str(_saved_image(tmp_path)))
    assert result.returncode == 0, result.stderr
    assert _selection(env) == (IMAGE_ID, TAG) and _tag_points_at(env) == IMAGE_ID


def test_a_failure_recording_the_selection_rolls_the_load_back(tmp_path: Path) -> None:
    """Review of #36: a failure after the checks, while recording the selection, must restore it and the tag."""
    env = {**_load_env(tmp_path, loads_as=IMAGE_ID, selected=OTHER_ID), "STUB_MV_FAIL": str(tmp_path / "mv-fail")}
    Path(env["STUB_MV_FAIL"]).touch()
    guest_mv = Path(env["STUB_GUEST_PATH"].split(os.pathsep)[0]) / "mv"
    guest_mv.write_text(  # the rename of the ID file fails once, after the tag file was already replaced
        '#!/bin/bash\nif [ -e "$STUB_MV_FAIL" ] && [ "${@: -1}" = .calibration-image ]; then\n'
        '  rm -f "$STUB_MV_FAIL"; exit 1\nfi\nexec /bin/mv "$@"\n',
        encoding="utf-8",
    )
    guest_mv.chmod(0o755)
    result = _run(env, "load-image", str(_saved_image(tmp_path)))
    assert result.returncode == 1 and "could not record" in result.stderr
    assert (
        "the previous selection is restored" in result.stderr and f"the selected image is {OTHER_ID}" in result.stderr
    )
    assert _selection(env) == (OTHER_ID, TAG) and _tag_points_at(env) == OTHER_ID
    assert _removed(env) == [IMAGE_ID]


VM_ADDRESS = "192.168.5.15"


def _host_block(
    env: dict[str, str],
    *,
    enabled: bool = True,
    probe: str = "blocked",
    counted_ports: str = "22 80 443 8080",
    container: str = "blocked",
) -> Path:
    """Stub the guest's side of the host block; returns the guest's fake /etc.

    ``probe`` is what each TCP probe sees ("blocked": No route to host, "open": it connects). A blocked probe to a
    port in ``counted_ports`` raises the reject rule's counter by 2, as the real rule does (a SYN and its retry);
    to any other port it fails without reaching the rule, as with an emptied or weakened table.

    ``container`` is what a probe from a container sees: "blocked" (refused, and the VM user's or the own-address
    counter rises; 10.0.2.2 has no route, by rootless Docker), "uncounted" (refused, no counter moves) or "open".
    """
    guest_bin = Path(env["STUB_GUEST_PATH"].split(os.pathsep)[0])
    etc = Path(env["STUB_GUEST_HOME"]) / "etc"
    (etc / "systemd" / "system").mkdir(parents=True)
    counter = Path(env["STUB_GUEST_HOME"]) / "reject-counter"
    user_counter = Path(env["STUB_GUEST_HOME"]) / "user-counter"
    local_counter = Path(env["STUB_GUEST_HOME"]) / "local-counter"
    for path in (counter, user_counter, local_counter):
        path.write_text("0", encoding="utf-8")
    real_docker = guest_bin / "docker.real"
    (guest_bin / "docker").rename(real_docker)
    bump = {"blocked": True, "uncounted": False, "open": False}[container]
    scripts = {
        # sudo runs the command with /etc mapped into the fake guest, so no test writes the real /etc
        "sudo": (
            '#!/bin/bash\n[ "$1" = -u ] && shift 2\nargs=()\n'
            f'for a in "$@"; do args+=("${{a//\\/etc\\//{etc}/}}"); done\nexec "${{args[@]}}"\n'
        ),
        "systemctl": f'#!/bin/sh\necho "systemctl $*" >> "$STUB_DOCKER_LOG"\nexit {0 if enabled else 1}\n',
        "nft": (
            '#!/bin/sh\necho "nft $*" >> "$STUB_DOCKER_LOG"\n'
            '[ "$1" = list ] && echo "meta skuid 65534 ip daddr { 10.0.0.0/8 } counter '
            f'packets $(cat {counter}) bytes 0"\n'
            '[ "$1" = list ] && echo "meta skuid $(id -u) ip daddr { 10.0.0.0/8 } counter '
            f'packets $(cat {user_counter}) bytes 0"\n'
            '[ "$1" = list ] && echo "ip daddr != 127.0.0.0/8 fib daddr type local counter '
            f'packets $(cat {local_counter}) bytes 0 reject"\n'
            "exit 0\n"
        ),
        "ip": (
            '#!/bin/sh\ncase "$*" in *route*) echo "default via 192.168.5.2 dev eth0 proto dhcp";; *) '
            f"echo '2: eth0    inet {VM_ADDRESS}/24 brd 192.168.5.255 scope global eth0'; "
            "echo '3: docker0    inet 172.17.0.1/16 brd 172.17.255.255 scope global docker0';; esac\n"
        ),
        # a container's /dev/tcp probe, answered like rootless Docker's network helper; anything else is docker
        "docker": (
            '#!/bin/bash\ncase "$*" in\n  *"/dev/tcp/"*)\n'
            '    all="$*"; target=${all##*/dev/tcp/}; address=${target%%/*}\n'
            + (
                "    exit 0;;\n"
                if container == "open"
                else '    if [ "$address" = 10.0.2.2 ]; then echo "bash: connect: No route to host"; exit 0; fi\n'
                # as on the real VM: docker0's address is the container's own gateway, refused inside its namespace
                '    if [ "$address" = 172.17.0.1 ]; then echo "bash: connect: Connection refused"; exit 0; fi\n'
                + (
                    f'    if [ "$address" = {VM_ADDRESS} ]; then c={local_counter}; else c={user_counter}; fi\n'
                    "    echo $(($(cat $c) + 1)) > $c\n"
                    if bump
                    else ""
                )
                + '    echo "bash: connect: Connection refused"; exit 0;;\n'
            )
            + f'esac\nexec {real_docker} "$@"\n'
        ),
        "timeout": (
            "#!/bin/sh\n"
            + (
                "port=${4##*/}; port=${port%% *}\n"
                f'case " {counted_ports} " in *" $port "*) echo $(($(cat {counter}) + 2)) > {counter};; esac\n'
                'echo "bash: connect: No route to host" >&2; exit 1\n'
                if probe == "blocked"
                else "exit 0\n"
            )
        ),
    }
    for name, body in scripts.items():
        (guest_bin / name).write_text(body, encoding="utf-8")
        (guest_bin / name).chmod(0o755)
    return etc


def test_a_paid_command_reapplies_the_host_block_and_proves_it_before_the_key(tmp_path: Path) -> None:
    env = _load_env(tmp_path, selected=IMAGE_ID)
    etc = _host_block(env)
    (etc / "mk-isolation.nft").write_text("table inet mk_isolation {}\n", encoding="utf-8")  # emptied by hand
    result = _run(env, "preflight")  # goes on to ask for the key, which a test has no terminal for
    assert "host block is not in place" not in result.stderr
    assert "20 of 20 probe(s) blocked by its reject rule" in result.stdout
    rules = (etc / "mk-isolation.nft").read_text(encoding="utf-8")  # this script's own copy, reapplied
    assert "reject with icmp type admin-prohibited" in rules and "ip daddr 192.168.5.2 udp dport { 53, 67 }" in rules
    assert f"nft -f {etc}/mk-isolation.nft" in Path(env["STUB_DOCKER_LOG"]).read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("block", "reason"),
    [
        ({"enabled": False}, "unit is not enabled"),
        ({"counted_ports": ""}, "did not block every probe through its own rule"),  # empty or weakened table
        # review: 20 probes, 20 counted in total, but only ports 22 and 80 reached the rule
        ({"counted_ports": "22 80"}, "did not block every probe through its own rule"),
        ({"probe": "open"}, "did not block every probe through its own rule"),
    ],
)
@pytest.mark.parametrize("mode", ["preflight", "calibrate"])
def test_a_paid_command_is_refused_before_the_key_unless_the_host_block_holds(
    tmp_path: Path, mode: str, block: dict[str, Any], reason: str
) -> None:
    """FR-015 isolation, review of the host block: an existing table is not enough; it must reject the probes."""
    env = _load_env(tmp_path, selected=IMAGE_ID)
    _host_block(env, **block)
    result = _run(env, mode)
    assert result.returncode == 1 and "host block is not in place" in result.stderr and reason in result.stderr
    assert "API key" not in result.stdout + result.stderr and "Type 'calibrate'" not in result.stdout
    assert "run " not in Path(env["STUB_DOCKER_LOG"]).read_text(encoding="utf-8")  # no container started


def _check_env(tmp_path: Path, *, forwarding: bool) -> dict[str, str]:
    """vm.sh check with the host block holding and the guest's egress stubbed; the port-forwarding probe server
    runs for real on this machine (the stub guest is local), so ``forwarding`` decides whether it starts."""
    env = {**_load_env(tmp_path, selected=IMAGE_ID), "HOME": str(tmp_path / "mac-home")}
    _host_block(env)
    ssh = Path(env["STUB_GUEST_HOME"]) / ".ssh"
    ssh.mkdir()
    (ssh / "authorized_keys").write_text("ssh-ed25519 AAAA lima\n", encoding="utf-8")
    guest_bin = Path(env["STUB_GUEST_PATH"].split(os.pathsep)[0])
    stubs = {
        "getent": "#!/bin/sh\necho '160.79.104.10   api.anthropic.com'\n",
        "curl": "#!/bin/sh\necho 'HTTP 401'\n",
        "setsid": '#!/bin/sh\n[ "$1" = -f ] && shift\n"$@" &\nexit 0\n' if forwarding else "#!/bin/sh\nexit 0\n",
    }
    for name, body in stubs.items():
        (guest_bin / name).write_text(body, encoding="utf-8")
        (guest_bin / name).chmod(0o755)
    return env


def test_check_reports_the_host_block_and_working_port_forwarding(tmp_path: Path) -> None:
    result = _run(_check_env(tmp_path, forwarding=True), "check")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "probe(s) blocked by its reject rule" in result.stdout and "HTTP 401" in result.stdout
    assert "copy: ok" in result.stdout and "port forwarding: ok" in result.stdout
    assert "container -> 172.17.0.1:22 blocked (the container's own gateway; no VM rule involved)" in result.stdout


def test_check_fails_when_port_forwarding_is_broken(tmp_path: Path) -> None:
    """The host block must not cost Lima's own channels; check proves both sides."""
    result = _run(_check_env(tmp_path, forwarding=False), "check")
    assert result.returncode == 1 and "port forwarding: FAILED" in result.stdout
    assert "do not run preflight or calibrate" in result.stderr


@pytest.mark.parametrize(
    ("container", "shown"),
    [("open", "NOT BLOCKED (connected, or no answer within 5 s)"), ("uncounted", "not by the rule")],
)
@pytest.mark.parametrize("mode", ["preflight", "calibrate"])
def test_a_paid_command_is_refused_when_a_container_gets_past_the_host_block(
    tmp_path: Path, mode: str, container: str, shown: str
) -> None:
    """Review of the host block: the agent runs in the container, so the container must be probed too."""
    env = _load_env(tmp_path, selected=IMAGE_ID)
    _host_block(env, container=container)
    result = _run(env, mode)
    assert result.returncode == 1 and "a container of the selected image got past it" in result.stderr
    assert shown in result.stderr and "API key" not in result.stdout + result.stderr


def test_container_probes_cover_the_mac_the_vm_itself_and_the_helpers_loopback(tmp_path: Path) -> None:
    env = _load_env(tmp_path, selected=IMAGE_ID)
    _host_block(env)
    result = _run(env, "preflight")
    assert "host block is not in place" not in result.stderr
    assert f"from a container of {IMAGE_ID}:" in result.stdout and "probe(s) blocked" in result.stdout
    runs = [line for line in Path(env["STUB_DOCKER_LOG"]).read_text(encoding="utf-8").splitlines() if "nft" in line]
    assert runs  # counters were read around the probes


def test_create_installs_the_host_block_before_any_image_exists(tmp_path: Path) -> None:
    """Review: create verifies the block from the VM; a container probe needs an image, which comes later."""
    env = _load_env(tmp_path)  # no image selected
    etc = _host_block(env)
    result = _run(env, "create")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "with the host block in place" in result.stdout and "probe(s) blocked by its reject rule" in result.stdout
    assert "from a container" not in result.stdout + result.stderr
    assert (etc / "mk-isolation.nft").is_file() and (etc / "systemd" / "system" / "mk-isolation.service").is_file()

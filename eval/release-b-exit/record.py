# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""Record one Release B exit run, bound to the bytes it executed (specs/memkernel-0-7-release-b-exit FR-003).

Standard library only. It follows wiki-studio's recording protocol (``examples/correction-loop/README.md`` at
wiki-studio commit ``2d5bf033d00fb7c57b1e1d3932a7586497bea9fb``), adapted to released wheels on both sides:

Preflight, which creates nothing: refuse unless the working tree is clean and ``--out`` does not exist; record
``HEAD``'s full commit SHA. The attempt then starts by creating ``--out``:
- archive that SHA, never the name ``HEAD``, and extract it;
- hash ``run.py``, this recorder and the protocol README from the extracted tree, and refuse if the running
  recorder differs;
- download memkernel ``--memkernel`` and wiki-studio ``--wiki-studio`` from PyPI. For ``--upgrade``, memkernel
  0.6.0 as well. Each wheel's sha256 is checked against the one PyPI publishes;
- install them into a fresh virtual environment and write its ``pip freeze``. For ``--upgrade`` that is 0.6.0, and
  the run installs the 0.7.x wheel itself halfway through;
- download the embedding model at the pinned revision, and refuse any other snapshot;
- run the extracted ``run.py`` once, never retried, with the hub offline, writing ``transcript.txt``;
- write ``manifest.json`` with the versions, the hashes, every check and the convergence summary.

Every attempt writes ``manifest.json`` as soon as ``--out`` exists (``outcome: running`` with the current
``stage``), and ends it as ``completed`` (with the run's exit code) or ``failed`` (with ``failed_stage`` and the
error). ``--out`` must not exist: a second attempt is a new directory, and a failed attempt is kept as it is.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

UPGRADE_FROM = "0.6.0"
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
EMBEDDING_REVISION = "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"
REPO_ROOT = Path(__file__).resolve().parents[2]
RUN_REL = Path("eval") / "release-b-exit" / "run.py"
RECORD_REL = Path("eval") / "release-b-exit" / "record.py"
PROTOCOL_REL = Path("eval") / "release-b-exit" / "README.md"


class CannotRunError(Exception):
    """The recorder cannot produce a valid run directory (exit 2)."""


def _utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _tail(text: str, limit: int = 400) -> str:
    return " ".join(text.split())[-limit:]


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _run(command: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(  # noqa: S603
            command, cwd=str(cwd) if cwd else None, capture_output=True, text=True, check=False
        )
    except OSError as exc:
        raise CannotRunError(f"could not run {command[0]}: {exc}") from exc


def _run_or_die(command: list[str], description: str) -> subprocess.CompletedProcess[str]:
    completed = _run(command)
    if completed.returncode != 0:
        raise CannotRunError(f"{description} failed (exit {completed.returncode}): {_tail(completed.stderr)}")
    return completed


def _extract_commit(tmp: Path, commit: str) -> Path:
    """The tree of ``commit`` (a full SHA), extracted: everything that produces evidence runs from it."""
    archive = tmp / "commit.tar"
    _run_or_die(
        ["git", "-C", str(REPO_ROOT), "archive", "--format=tar", "--output", str(archive), commit],
        f"git archive {commit}",
    )
    source = tmp / "source"
    source.mkdir()
    try:
        with tarfile.open(archive) as tar:
            tar.extractall(source, filter="data")
    except (tarfile.TarError, OSError) as exc:
        raise CannotRunError(f"could not extract the archive of {commit}: {exc}") from exc
    return source


def _published_sha256(project: str, version: str, filename: str) -> str:
    url = f"https://pypi.org/pypi/{project}/{version}/json"
    try:
        with urllib.request.urlopen(url, timeout=30) as response:  # noqa: S310 — a fixed https URL
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError) as exc:
        raise CannotRunError(f"PyPI could not be read at {url}: {exc}") from exc
    for entry in payload.get("urls", []):
        if entry.get("filename") == filename and entry.get("digests", {}).get("sha256"):
            return str(entry["digests"]["sha256"])
    raise CannotRunError(f"PyPI lists no sha256 for {filename} in {project} {version}")


def _download(tmp: Path, project: str, version: str) -> dict[str, Any]:
    """One wheel from PyPI, refused unless its sha256 equals the one PyPI publishes."""
    dest = tmp / "downloads" / f"{project}-{version}"
    _run_or_die(
        [
            sys.executable,
            "-m",
            "pip",
            "download",
            f"{project}=={version}",
            "--no-deps",
            "--only-binary",
            ":all:",
            "--dest",
            str(dest),
        ],
        f"pip download {project}=={version}",
    )
    wheels = sorted(dest.glob("*.whl"))
    if len(wheels) != 1:
        raise CannotRunError(f"pip download wrote {len(wheels)} wheels for {project} {version}, expected one")
    downloaded = _sha256_file(wheels[0])
    published = _published_sha256(project, version, wheels[0].name)
    if downloaded != published:
        raise CannotRunError(f"{wheels[0].name} has sha256 {downloaded}, but PyPI publishes {published}")
    return {"path": wheels[0], "file": wheels[0].name, "sha256": downloaded, "pypi_sha256": published}


def _venv_python(venv: Path) -> Path:
    return venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _install(venv: Path, wheels: list[Path]) -> Path:
    python = _venv_python(venv)
    _run_or_die([sys.executable, "-m", "venv", str(venv)], "python -m venv")
    pip = [str(python), "-m", "pip"]
    _run_or_die([*pip, "install", "--quiet", "--upgrade", "pip"], "pip install --upgrade pip")
    _run_or_die([*pip, "install", "--quiet", *[str(w) for w in wheels]], "pip install the wheels")
    _run_or_die([*pip, "check"], "pip check")
    return python


def _versions(python: Path) -> dict[str, str]:
    snippet = (
        "import json, platform\nfrom importlib import metadata\n"
        "print(json.dumps({'memkernel': metadata.version('memkernel'), 'wiki_studio': metadata.version('wiki-studio'),"
        " 'python': platform.python_version(), 'platform': platform.platform()}))\n"
    )
    return {
        k: str(v) for k, v in json.loads(_run_or_die([str(python), "-c", snippet], "the version probe").stdout).items()
    }


def _embedding_snapshot(python: Path, revision: str) -> Path:
    snippet = (
        "import sys\nfrom huggingface_hub import snapshot_download\n"
        f"print(snapshot_download({EMBEDDING_MODEL!r}, revision=sys.argv[1]))\n"
    )
    snapshot = Path(_run_or_die([str(python), "-c", snippet, revision], "snapshot_download").stdout.strip())
    if snapshot.name != revision or not snapshot.is_dir():
        raise CannotRunError(f"the snapshot is {snapshot}, not the pinned revision {revision}")
    return snapshot


def _run_once(python: Path, out: Path, tmp: Path, snapshot: Path, source: Path, extra: list[str]) -> tuple[int, Any]:
    """The run, once, never retried, with the pinned model and the hub offline."""
    summary_path = tmp / "summary.json"
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env["MEMKERNEL_EMBEDDING_MODEL"] = str(snapshot)
    env["HF_HUB_OFFLINE"] = "1"
    command = [str(python), str(source / RUN_REL), "--workdir", str(tmp / "work"), "--summary", str(summary_path)]
    with (out / "transcript.txt").open("w", encoding="utf-8") as transcript:
        completed = subprocess.run(  # noqa: S603
            [*command, *extra], cwd=str(source), env=env, stdout=transcript, stderr=subprocess.STDOUT, check=False
        )
    summary = None
    if summary_path.is_file():
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
        except ValueError:  # a run killed while writing it: the exit code and the transcript still stand
            summary = None
    return completed.returncode, summary


def _write_manifest(out: Path, manifest: dict[str, Any]) -> None:
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str) + "\n", encoding="utf-8")


def _record(out: Path, memkernel: str, wiki_studio: str, upgrade: bool, revision: str) -> int:
    started_at = _utc_now()
    if out.exists():
        raise CannotRunError(f"--out {out} already exists; a second attempt is a new directory")
    status = _run(["git", "-C", str(REPO_ROOT), "status", "--porcelain"])
    if status.returncode != 0 or status.stdout.strip():
        raise CannotRunError(f"the working tree is not clean: {_tail(status.stdout or status.stderr)}")
    head = _run_or_die(["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"], "git rev-parse").stdout.strip()

    out.mkdir(parents=True)  # the attempt starts here; every way out leaves a manifest
    manifest: dict[str, Any] = {
        "outcome": "running",
        "kind": "upgrade" if upgrade else "main",
        "git_commit": head,
        "started_at": started_at,
        "embedding_model": EMBEDDING_MODEL,
        "embedding_revision": revision,
    }
    stage = "extract"

    def enter(name: str) -> None:
        nonlocal stage
        stage = name
        manifest["stage"] = name
        _write_manifest(out, manifest)

    enter("extract")
    try:
        with tempfile.TemporaryDirectory(prefix="memkernel-exit-record-") as tmp_name:
            tmp = Path(tmp_name)
            source = _extract_commit(tmp, head)
            manifest["run_sha256"] = _sha256_file(source / RUN_REL)
            manifest["record_sha256"] = _sha256_file(source / RECORD_REL)
            manifest["protocol_sha256"] = _sha256_file(source / PROTOCOL_REL)
            if _sha256_file(Path(__file__).resolve()) != manifest["record_sha256"]:
                raise CannotRunError(f"the running record.py differs from the one in commit {head}")
            enter("download")
            target = _download(tmp, "memkernel", memkernel)
            studio = _download(tmp, "wiki-studio", wiki_studio)
            wheels = {"memkernel": target, "wiki-studio": studio}
            if upgrade:
                wheels["memkernel-upgrade-from"] = _download(tmp, "memkernel", UPGRADE_FROM)
            manifest["wheels"] = {k: {kk: vv for kk, vv in v.items() if kk != "path"} for k, v in wheels.items()}
            enter("install")
            first = wheels["memkernel-upgrade-from"]["path"] if upgrade else target["path"]
            python = _install(tmp / "venv", [first, studio["path"]])
            (out / "environment.txt").write_text(_run_or_die([str(python), "-m", "pip", "freeze"], "pip freeze").stdout)
            manifest["versions_installed"] = _versions(python)
            enter("embedding")
            snapshot = _embedding_snapshot(python, revision)
            enter("run")
            extra = ["--upgrade", "--upgrade-to", str(target["path"])] if upgrade else []
            exit_code, summary = _run_once(python, out, tmp, snapshot, source, extra)
            manifest["versions_after"] = _versions(python)
            manifest["exit_code"] = exit_code
            manifest["checks"] = summary.get("checks") if summary else None
            manifest["convergence"] = (
                {
                    step: values.get("summary")
                    for step, values in summary.get("steps", {}).items()
                    if "summary" in values
                }
                if summary
                else None
            )
            manifest.pop("stage", None)
            manifest["outcome"] = "completed"
            manifest["finished_at"] = _utc_now()
            _write_manifest(out, manifest)
    except BaseException as exc:  # every way out, KeyboardInterrupt included, leaves a manifest
        manifest.pop("stage", None)
        manifest["outcome"] = "failed"
        manifest["failed_stage"] = stage
        manifest["error"] = f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__
        manifest["finished_at"] = _utc_now()
        _write_manifest(out, manifest)
        raise
    return exit_code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="record.py", description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, required=True, help="the run directory to create")
    parser.add_argument("--memkernel", required=True, help="the released memkernel version, e.g. 0.7.0")
    parser.add_argument("--wiki-studio", required=True, help="the released wiki-studio version, e.g. 0.8.1")
    parser.add_argument("--upgrade", action="store_true", help=f"the upgrade run: from memkernel {UPGRADE_FROM}")
    parser.add_argument("--embedding-revision", default=EMBEDDING_REVISION)
    args = parser.parse_args(argv)
    try:
        return _record(
            args.out.expanduser().absolute(), args.memkernel, args.wiki_studio, args.upgrade, args.embedding_revision
        )
    except (CannotRunError, OSError) as exc:
        print(f"cannot run: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

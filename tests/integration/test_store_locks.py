# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""Store locks across real processes (memkernel-0-7-store-locks SC-1, SC-1a, SC-2).

Each child is a fresh interpreter that opens the store itself. The parent steers the order with marker files, so a
case asserts what happened while another process held a lock, not how long anything took.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.integration

_WAIT = 30.0  # generous: a child imports chromadb before it does anything
_STILL_BLOCKED = 0.5  # how long a taker must stay blocked while another process holds the lock

_CHILD = r"""
import json, logging, sys, time
from datetime import UTC, datetime
from pathlib import Path

import chromadb

from memkernel.config import MemKernelSettings
from memkernel.storage import chroma
from memkernel.storage.chroma import ChromaVectorStore

mode, store_dir, marks = sys.argv[1], sys.argv[2], Path(sys.argv[3])
logging.basicConfig(level=logging.INFO, stream=sys.stderr)


def mark(name):
    (marks / name).write_text(str(time.time()))


def wait_for(name):
    deadline = time.time() + 60
    while not (marks / name).exists():
        if time.time() > deadline:
            raise SystemExit(f"timed out waiting for {name}")
        time.sleep(0.02)


def open_store(inject):
    settings = MemKernelSettings(project_id="locks", chroma_persist_path="" if inject else store_dir)
    client = chromadb.PersistentClient(path=store_dir) if inject else None
    return ChromaVectorStore(settings, client=client)


if mode in ("hold", "hold-injected"):
    store = open_store(mode == "hold-injected")
    with store.exclusive("wiki-import"):
        mark("held")
        wait_for("release")
elif mode in ("take", "take-injected"):
    if len(sys.argv) > 4:
        chroma.LOCK_WAIT_LOG_SECONDS = float(sys.argv[4])
    store = open_store(mode == "take-injected")
    mark("trying")
    with store.exclusive("wiki-import"):
        mark("got")
elif mode == "seed":
    store = open_store(len(sys.argv) > 5 and sys.argv[5] == "injected")
    metadata = {"project_id": "locks", "session_id": "s", "type": "fact", "hash": "h", "token_count": 1,
                "source": "t", "timestamp": datetime.now(UTC), "tags": "seed"}
    store.upsert(sys.argv[4], "seeded", [0.6, 0.8], metadata)
elif mode == "read-other":
    store = open_store(not (len(sys.argv) > 5 and sys.argv[5] == "injected"))
    print(json.dumps(store.get_by_id(sys.argv[4]) is not None))
elif mode == "merge-paused":
    store = open_store(False)
    real = ChromaVectorStore._read_tags

    def paused(self, ref_id):
        tags = real(self, ref_id)
        mark("read")
        wait_for("go")
        return tags

    ChromaVectorStore._read_tags = paused
    store.merge_tags(sys.argv[4], add=["from-a"])
elif mode == "merge":
    store = open_store(False)
    mark("merge-trying")
    store.merge_tags(sys.argv[4], add=["from-b"])
    mark("merge-done")
elif mode == "touch":
    store = open_store(False)
    store.update_metadata(sys.argv[4], {"last_accessed": "2026-11-03T00:00:00+00:00", "access_count": 7})
    mark("touch-done")
elif mode == "show":
    store = open_store(False)
    memory = store.get_by_id(sys.argv[4])
    print(json.dumps({"tags": memory.tags, "access_count": memory.access_count}))
"""


def _child(mode: str, store_dir: Path, marks: Path, *extra: str, state_dir: str = "") -> subprocess.Popen[str]:
    env = {**os.environ, "MEMKERNEL_STATE_DIR": state_dir or str(marks / f"state-{mode}")}
    return subprocess.Popen(  # noqa: S603
        [sys.executable, "-c", _CHILD, mode, str(store_dir), str(marks), *extra],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )


def _wait_for(marks: Path, name: str, *procs: subprocess.Popen[str]) -> None:
    deadline = time.time() + _WAIT
    while not (marks / name).exists():
        for proc in procs:
            if proc.poll() not in (None, 0):
                raise AssertionError(f"child exited {proc.returncode}: {proc.stderr.read() if proc.stderr else ''}")
        assert time.time() < deadline, f"timed out waiting for {name}"
        time.sleep(0.02)


def _finish(*procs: subprocess.Popen[str]) -> list[str]:
    outs = []
    for proc in procs:
        out, err = proc.communicate(timeout=_WAIT)
        assert proc.returncode == 0, err
        outs.append(out + err)
    return outs


def _still_absent(marks: Path, name: str) -> bool:
    deadline = time.time() + _STILL_BLOCKED
    while time.time() < deadline:
        if (marks / name).exists():
            return False
        time.sleep(0.02)
    return True


def _run(mode: str, store_dir: Path, marks: Path, *extra: str) -> str:
    return _finish(_child(mode, store_dir, marks, *extra))[0]


@pytest.mark.parametrize(("hold", "take"), [("hold", "take"), ("hold-injected", "take-injected")])
def test_two_processes_on_one_store_serialize(hold: str, take: str, tmp_path: Path) -> None:
    """SC-1: one persist directory, two state directories (and, injected, two clients): the second waits."""
    store_dir, marks = tmp_path / "chroma", tmp_path / "marks"
    marks.mkdir()
    if hold == "hold-injected":  # first, the two kinds of client share data both ways, so it can't pass vacuously
        for ref, written_by in (("seeded-1", "configured"), ("seeded-2", "injected")):
            _run("seed", store_dir, marks, ref, written_by)
            assert _run("read-other", store_dir, marks, ref, written_by).strip().splitlines()[-1] == "true"
    holder = _child(hold, store_dir, marks, state_dir=str(tmp_path / "state-a"))
    _wait_for(marks, "held", holder)
    taker = _child(take, store_dir, marks, state_dir=str(tmp_path / "state-b"))
    _wait_for(marks, "trying", taker)
    assert _still_absent(marks, "got")  # blocked while the other process holds the lock
    (marks / "release").touch()
    _wait_for(marks, "got", taker)
    _finish(holder, taker)


def test_a_long_wait_across_processes_is_logged(tmp_path: Path) -> None:
    """SC-1a: a take that waits past LOCK_WAIT_LOG_SECONDS logs one info line, then acquires."""
    store_dir, marks = tmp_path / "chroma", tmp_path / "marks"
    marks.mkdir()
    holder = _child("hold", store_dir, marks)
    _wait_for(marks, "held", holder)
    taker = _child("take", store_dir, marks, "0.1")
    _wait_for(marks, "trying", taker)
    assert _still_absent(marks, "got")
    (marks / "release").touch()
    _, taken = _finish(holder, taker)
    assert taken.count("waiting for store lock wiki-import") == 1


def test_a_tag_added_meanwhile_is_never_lost(tmp_path: Path) -> None:
    """SC-2: with A's merge paused after its read, B's touch completes and B's merge waits; nothing is lost."""
    store_dir, marks = tmp_path / "chroma", tmp_path / "marks"
    marks.mkdir()
    _run("seed", store_dir, marks, "r")
    a = _child("merge-paused", store_dir, marks, "r")
    _wait_for(marks, "read", a)
    _finish(_child("touch", store_dir, marks, "r"))  # update_metadata needs no lock: it never writes tags
    b = _child("merge", store_dir, marks, "r")
    _wait_for(marks, "merge-trying", b)
    assert _still_absent(marks, "merge-done")  # B's merge waits for A's
    (marks / "go").touch()
    _finish(a, b)
    shown = _run("show", store_dir, marks, "r").strip().splitlines()[-1]
    assert shown == '{"tags": ["seed", "from-a", "from-b"], "access_count": 7}'

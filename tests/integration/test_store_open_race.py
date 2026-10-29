# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""Two processes open one new store at the same instant (memkernel-0-6-store-open-race SC-3, SC-4; #69).

Before the open lock, 10 of 120 such opens failed with "table collections already exists".
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.integration, pytest.mark.slow]

TRIALS = 60

_OPEN_WRITE_READ = """
import json, sys, time
from datetime import UTC, datetime
from memkernel.config import MemKernelSettings
from memkernel.storage.chroma import ChromaVectorStore
path, start, who, other = sys.argv[1], float(sys.argv[2]), sys.argv[3], sys.argv[4]
while time.time() < start:
    pass
store = ChromaVectorStore(MemKernelSettings(project_id="race", chroma_persist_path=path))
metadata = {"project_id": "race", "session_id": "s", "type": "fact", "hash": who, "token_count": 1,
            "source": who, "timestamp": datetime.now(UTC)}
store.upsert(who, f"written by {who}", [0.6, 0.8], metadata)
deadline = time.time() + 10
while store.get_by_id(other) is None and time.time() < deadline:
    time.sleep(0.05)
print(json.dumps({"seen": sorted(m.ref_id for m in store.list_all()),
                  "collections": len(store._client.list_collections())}))
"""


def test_two_processes_open_one_new_store_at_once_and_share_it(tmp_path: Path) -> None:
    failures: list[str] = []
    for trial in range(TRIALS):
        path = str(tmp_path / f"store-{trial}")
        start = f"{time.time() + 1.0}"
        procs = [
            subprocess.Popen(  # noqa: S603
                [sys.executable, "-c", _OPEN_WRITE_READ, path, start, who, other],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            for who, other in (("a", "b"), ("b", "a"))
        ]
        for proc in procs:
            out, err = proc.communicate(timeout=60)
            if proc.returncode != 0:
                failures.append(f"trial {trial}: exit {proc.returncode}: {err.strip().splitlines()[-1:]}")
                continue
            result = json.loads(out)
            if result != {"seen": ["a", "b"], "collections": 1}:  # SC-4: one collection, each reads the other's write
                failures.append(f"trial {trial}: {result}")

    assert failures == []

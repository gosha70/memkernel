# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""Concurrent wiki imports across real processes (memkernel-0-7-wiki-scope SC-8).

Each child opens one persistent store and runs the ungoverned import; the store's import lock makes the imports
run one after the other, whichever starts first.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import uuid
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.integration

_WAIT = 60.0
REL = "decisions/pg.md"
PAGE = "---\npage_type: decision\nslug: pg\ntitle: Use Postgres\nstatus: stable\n---\n\nBecause of concurrent writes.\n"

_CHILD = r"""
import json, sys, time
from pathlib import Path

from memkernel.config import MemKernelSettings
from memkernel.core.models import MemoryType
from memkernel.core.services import MemoryService
from memkernel.retrieval.search import HybridSearchService
from memkernel.retrieval.sparse import BM25Index
from memkernel.storage.chroma import ChromaVectorStore
from memkernel.wiki import sync
from tests.conftest import MockEmbedding

mode, root, store_dir, start = sys.argv[1], Path(sys.argv[2]), sys.argv[3], float(sys.argv[4])
settings = MemKernelSettings(project_id="scope", chroma_persist_path=store_dir, state_dir=str(root / "state"))
store, sparse = ChromaVectorStore(settings), BM25Index()
search = HybridSearchService(store, MockEmbedding(), sparse, settings)
svc = MemoryService(store, MockEmbedding(), sparse, search, settings)
if mode == "seed":
    text = "Use Postgres\n\nBecause of concurrent writes."
    print(svc.retain(text, MemoryType.DECISION, source=sys.argv[5], tags=["wiki"]))
    raise SystemExit
sync.gate_available = lambda: None  # the ungoverned import: no wiki-studio in the child
adopt = json.loads(sys.argv[6]) if len(sys.argv) > 6 else None
while time.time() < start:
    time.sleep(0.01)
report = sync.WikiImporter(svc, root / sys.argv[5], project_root=root).import_pages(adopt_pages=adopt)
print(json.dumps({"imported": report.imported, "unchanged": report.unchanged, "ambiguous": report.ambiguous,
                  "error": report.import_error}))
"""


def _run(*args: str) -> subprocess.Popen[str]:
    return subprocess.Popen(  # noqa: S603
        [sys.executable, "-c", _CHILD, *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=dict(os.environ),
    )


def _result(proc: subprocess.Popen[str]) -> Any:
    out, err = proc.communicate(timeout=_WAIT)
    assert proc.returncode == 0, err
    return json.loads(out.strip().splitlines()[-1])


def _wiki(root: Path, name: str, wiki_id: str | None) -> None:
    wiki = root / name
    (wiki / "decisions").mkdir(parents=True)
    (wiki / REL).write_text(PAGE)
    if wiki_id is not None:
        (wiki / ".wiki-studio.json").write_text(json.dumps({"manifest_version": 1, "wiki_id": wiki_id}))


def _store(root: Path) -> list[Any]:
    from memkernel.config import MemKernelSettings
    from memkernel.storage.chroma import ChromaVectorStore

    settings = MemKernelSettings(project_id="scope", chroma_persist_path=str(root / "chroma"))
    return [m for m in ChromaVectorStore(settings).list_all() if not m.retired()]


def test_two_wikis_adopting_one_record_at_once_adopt_it_once(tmp_path: Path) -> None:
    ids = {"a": str(uuid.uuid4()), "b": str(uuid.uuid4())}
    for name, wiki_id in ids.items():
        _wiki(tmp_path, name, wiki_id)
    store_dir = str(tmp_path / "chroma")
    seed = _run("seed", str(tmp_path), store_dir, "0", REL)
    out, err = seed.communicate(timeout=_WAIT)
    assert seed.returncode == 0, err
    legacy = out.strip().splitlines()[-1]
    adopt = json.dumps([{"path": REL, "ref_id": legacy}])
    start = f"{time.time() + 3.0}"

    results = [_result(p) for p in [_run("import", str(tmp_path), store_dir, start, name, adopt) for name in ids]]

    reasons = sorted(e["reason"] for r in results for e in r["ambiguous"])
    assert reasons == ["candidate changed"], results  # exactly one adopted it; the other was refused
    (record,) = [m for m in _store(tmp_path) if m.ref_id == legacy]
    assert len([t for t in record.tags if t.startswith("wiki-id:")]) == 1


def test_two_imports_of_one_wiki_at_once_write_one_record(tmp_path: Path) -> None:
    _wiki(tmp_path, "wiki", None)
    store_dir = str(tmp_path / "chroma")
    start = f"{time.time() + 3.0}"

    results = [_result(p) for p in [_run("import", str(tmp_path), store_dir, start, "wiki") for _ in range(2)]]

    assert sorted(len(r["imported"]) for r in results) == [1, 1]  # the second deduped into the first's record
    assert len([m for m in _store(tmp_path) if m.source == REL]) == 1

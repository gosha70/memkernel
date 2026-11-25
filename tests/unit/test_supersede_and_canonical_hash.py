# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""Supersede suggestions and canonical hashing (memkernel-0-17-supersede-and-canonical-hash, #153)."""

from __future__ import annotations

import importlib.util
import json
import math
import sys
import uuid
from pathlib import Path
from typing import Any

import chromadb
import pytest

from memkernel import recall_log
from memkernel.config import MemKernelSettings
from memkernel.core.models import (
    HASH_SCHEME_CANONICAL,
    HASH_SCHEME_KEY,
    HASH_SCHEME_RAW,
    SOURCE_HASH_KEY,
    Caller,
    MemoryType,
    SupersedeSuggestion,
)
from memkernel.core.services import _hashes
from memkernel.factory import build_service
from memkernel.memory.dedup import canonical_form, compute_content_hash
from memkernel.wiki.pages import parse_page
from memkernel.wiki.sync import WikiExporter
from tests.conftest import MockEmbedding

pytestmark = pytest.mark.unit

A = Caller(agent_id="a")
B = Caller(agent_id="b")
RUN = "run-153"


class KeyedEmbedding:
    """Chosen texts get chosen vectors (so closeness is exact); any other text gets a vector orthogonal to them."""

    def __init__(self, vectors: dict[str, list[float]]) -> None:
        self._vectors = vectors

    def embed(self, texts: list[str]) -> list[list[float]]:
        out = []
        for text in texts:
            v = self._vectors.get(text, [0.0, 0.0, 0.0, 1.0])
            norm = math.sqrt(sum(x * x for x in v))
            out.append([x / norm for x in v])
        return out

    @property
    def dimension(self) -> int:
        return 4


def _settings(tmp_path: Path, **overrides: Any) -> MemKernelSettings:
    base: dict[str, Any] = {
        "project_id": f"s4-{uuid.uuid4().hex[:8]}",
        "chroma_persist_path": str(tmp_path / "chroma"),
        "state_dir": str(tmp_path / "state"),
        "project_root": str(tmp_path / "project"),
    }
    base.update(overrides)
    (tmp_path / "project").mkdir(exist_ok=True)
    return MemKernelSettings(**base)


def _service(settings: MemKernelSettings, embedding: Any = None) -> Any:
    return build_service(settings, embedding=embedding or MockEmbedding(), chroma_client=chromadb.EphemeralClient())


@pytest.fixture
def svc(tmp_path: Path) -> Any:
    return _service(_settings(tmp_path))


def _make_written_before(svc: Any, ref_id: str, source_text: str | None = None) -> None:
    """Rewrite a record as memkernel 0.9.0 and earlier wrote it: a raw hash, no scheme (and a raw source hash)."""
    memory = svc.get(ref_id, touch=False)
    update: dict[str, Any] = {"hash": compute_content_hash(memory.content, HASH_SCHEME_RAW), HASH_SCHEME_KEY: ""}
    if source_text is not None:
        update[SOURCE_HASH_KEY] = compute_content_hash(source_text, HASH_SCHEME_RAW)
    svc._vector_store.update_metadata(ref_id, update)
    assert svc.get(ref_id, touch=False).hash_scheme == HASH_SCHEME_RAW


# --- D5: the canonical form ---------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "form"),
    [
        ("﻿Use Postgres.", "Use Postgres."),  # a leading byte-order mark
        ("Use Postgres.\r\nThen Redis.\r\n", "Use Postgres.\nThen Redis."),  # Windows line endings
        ("Use Postgres.\rThen Redis.", "Use Postgres.\nThen Redis."),  # old Mac line endings
        ("Use Postgres.  \t\nThen Redis.\t", "Use Postgres.\nThen Redis."),  # trailing spaces and tabs
        ("\n\n  \nUse Postgres.\n\n\n", "Use Postgres."),  # blank lines at both ends
        ("Café", "Café"),  # Unicode NFC
        ("Use  Postgres.", "Use  Postgres."),  # inner spaces kept
        ("def f():\n    return 1", "def f():\n    return 1"),  # indentation kept
        ("USE postgres.", "USE postgres."),  # case kept
    ],
)
def test_the_canonical_form(text: str, form: str) -> None:
    assert canonical_form(text) == form


def test_an_unknown_scheme_is_refused() -> None:
    with pytest.raises(ValueError, match="unknown content hash scheme"):
        compute_content_hash("x", "md5")


# --- FR-002, D6: new records, stored text, dedup ----------------------------------------------------------------


def test_a_new_record_is_canonical_and_its_text_is_stored_as_given(svc: Any) -> None:
    ref = svc.retain("Use Postgres.  \r\n", MemoryType.DECISION)
    memory = svc.get(ref, touch=False)
    assert memory.content == "Use Postgres.  \r\n"  # only the hash uses the normalised form
    assert memory.hash_scheme == HASH_SCHEME_CANONICAL
    assert memory.content_hash == compute_content_hash("Use Postgres.", HASH_SCHEME_CANONICAL)


def test_texts_differing_only_by_the_form_are_one_record_and_others_two(svc: Any) -> None:
    first = svc.retain("Use Postgres.\r\n", MemoryType.DECISION)
    assert svc.retain("﻿Use Postgres.  ", MemoryType.DECISION) == first
    assert svc.retain("Use  Postgres.", MemoryType.DECISION) != first
    assert svc.retain("use postgres.", MemoryType.DECISION) != first


def test_a_written_before_record_dedups_only_byte_identical_text(svc: Any) -> None:
    old = svc.retain("Use Redis.", MemoryType.DECISION)
    _make_written_before(svc, old)
    assert svc.retain("Use Redis.", MemoryType.DECISION) == old  # confirmed under its own (raw) scheme
    assert svc.retain("Use Redis.  ", MemoryType.DECISION) != old  # a raw hash cannot match a canonical form


def test_a_canonical_match_wins_over_a_raw_one_after_eligibility(svc: Any) -> None:
    old = svc.retain("Use Kafka.", MemoryType.DECISION)
    _make_written_before(svc, old)
    canonical = svc.retain("Use Kafka.  ", MemoryType.DECISION)  # not byte-identical: a new canonical record
    assert canonical != old
    assert svc.retain("Use Kafka.", MemoryType.DECISION) == canonical  # both confirm: canonical preferred


def test_an_ineligible_canonical_record_never_wins_over_an_eligible_raw_one(svc: Any) -> None:
    old = svc.retain("Use NATS.", MemoryType.DECISION)
    _make_written_before(svc, old)
    svc.retain("Use NATS.  ", MemoryType.DECISION, scope="agent", caller=A)  # canonical, in another scope
    assert svc.retain("Use NATS.", MemoryType.DECISION, caller=B) == old  # scope first, then the scheme


def test_with_the_owner_check_a_raw_and_a_canonical_record_resolve_to_the_canonical_one(svc: Any) -> None:
    old = svc.retain("A wiki page body.", MemoryType.DECISION)
    _make_written_before(svc, old)
    canonical = svc.retain("A wiki page body.  ", MemoryType.DECISION)
    hit = svc._dedup_hit(_hashes("A wiki page body."), MemoryType.DECISION, None, lambda m: True, "project")
    assert hit is not None and hit.ref_id == canonical  # not AmbiguousDedupError


def test_a_written_before_code_record_dedups_an_identical_file(svc: Any) -> None:
    code = "def handler():\n    return 1\n"
    old = svc.retain(code, MemoryType.CODE, source="app.py")
    _make_written_before(svc, old)
    assert svc.retain(code, MemoryType.CODE, source="app.py") == old
    assert svc.get(old, touch=False).superseded_by is None


# --- FR-003: every comparison in each memory's own scheme --------------------------------------------------------


def test_revalidation_hashes_each_record_in_its_own_scheme(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    svc = _service(settings)
    root = Path(settings.project_root)
    text = "def handler():\n    return 1\n"
    (root / "old.py").write_text(text, encoding="utf-8")
    (root / "new.py").write_text(text, encoding="utf-8")
    (root / "notes.md").write_text("Use Postgres.\n", encoding="utf-8")
    old = svc.retain(text, MemoryType.CODE, source="old.py")
    _make_written_before(svc, old)
    new = svc.retain(text, MemoryType.CODE, source="new.py")
    decision = svc.retain("Use Postgres.", MemoryType.DECISION, source="notes.md")
    assert svc.consolidate(revalidate=True, purge=False)["revalidated"]["flagged"] == []  # no scheme mismatch

    whitespace_only = "def handler():  \r\n    return 1\r\n"
    for name in ("old.py", "new.py"):
        (root / name).write_text(whitespace_only, encoding="utf-8")
    (root / "notes.md").write_text("Use Postgres.   \r\n\r\n", encoding="utf-8")
    flagged = {i["ref_id"] for i in svc.consolidate(revalidate=True, purge=False)["revalidated"]["flagged"]}
    assert flagged == {old}  # whitespace-only edits flag only the raw record; new code and decision are not flagged
    assert decision not in flagged and new not in flagged

    (root / "new.py").write_text("def handler():\n    return 2\n", encoding="utf-8")
    flagged = {i["ref_id"] for i in svc.consolidate(revalidate=True, purge=False)["revalidated"]["flagged"]}
    assert new in flagged  # a real change still flags


def test_receipts_name_each_records_scheme(tmp_path: Path) -> None:
    settings = _settings(tmp_path, recall_log=True)
    svc = _service(settings)
    old = svc.retain("An old fact.", MemoryType.FACT)
    _make_written_before(svc, old)
    new = svc.retain("A new fact.", MemoryType.FACT)
    memories = [svc.get(r, touch=False) for r in (old, new)]
    recall_log.append(settings, recall_log.ORIGIN_TOOL, [old, new], query="q", memories=memories)
    path = recall_log.log_path(settings)
    assert path is not None
    (record,) = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert [m["content_hash_scheme"] for m in record["memories"]] == [HASH_SCHEME_RAW, HASH_SCHEME_CANONICAL]


def _diff_module() -> Any:
    path = Path(__file__).resolve().parents[2] / "eval" / "context-diff" / "diff.py"
    spec = importlib.util.spec_from_file_location("context_diff_153", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_the_context_diff_compares_each_memory_in_its_own_scheme(tmp_path: Path) -> None:
    settings = _settings(tmp_path, recall_log=True)
    svc = _service(settings)
    root = Path(settings.project_root)
    old = svc.retain("An old fact.", MemoryType.FACT)
    _make_written_before(svc, old)
    new = svc.retain("A new fact.", MemoryType.FACT)
    source = "def first():\n    return 1\n\n\ndef second():\n    return 2\n"
    (root / "lib.py").write_text(source, encoding="utf-8")
    owner = svc.retain(source, MemoryType.CODE, source="lib.py")
    (chunk,) = svc._vector_store.list_all({"parent_ref": owner}, include_content=False)[:1]
    refs = [old, new, chunk.ref_id]
    recall_log.append(
        settings,
        recall_log.ORIGIN_TOOL,
        refs,
        query="q",
        ids=recall_log.Correlation(RUN),
        memories=[svc.get(r, touch=False) for r in refs],
    )
    (root / "lib.py").write_text(source.replace("\n", "  \r\n"), encoding="utf-8")  # whitespace-only edit
    report = _diff_module().diff(settings, RUN, store=svc._vector_store, root=root)
    statuses = {m["ref_id"]: m["statuses"] for m in report["memories"]}
    assert statuses == {old: ["unchanged"], new: ["unchanged"], chunk.ref_id: ["unchanged"]}  # no false rehashed


def test_exported_pages_name_the_scheme(tmp_path: Path) -> None:
    settings = _settings(tmp_path, wiki_mode="ungated")
    svc = _service(settings)
    svc.retain("Use Postgres for the user store.", MemoryType.DECISION)
    report = WikiExporter(svc, tmp_path / "wiki").export()
    (written,) = report.written
    page = parse_page((tmp_path / "wiki" / written).read_text(encoding="utf-8"))
    assert page is not None and page.extra["memkernel_hash_scheme"] == HASH_SCHEME_CANONICAL


# --- FR-001, D1–D4: supersede suggestions ------------------------------------------------------------------------

OLD = "Use PostgreSQL 15 for the user database."
NEW = "Use PostgreSQL 16 for the user database."
FAR = "Store uploaded images in S3."


@pytest.fixture
def keyed(tmp_path: Path) -> Any:
    vectors = {OLD: [1.0, 0.0, 0.0, 0.0], NEW: [1.0, 0.3, 0.0, 0.0], FAR: [0.0, 1.0, 0.0, 0.0]}
    return _service(_settings(tmp_path), KeyedEmbedding(vectors))


def _suggest(svc: Any, text: str, type: MemoryType = MemoryType.DECISION, **kw: Any) -> tuple[str, list[Any]]:  # noqa: A002
    found: list[SupersedeSuggestion] = []
    ref = svc.retain(text, type, suggestions=found, **kw)
    return ref, found


def test_a_close_live_record_is_suggested_and_nothing_is_superseded(keyed: Any) -> None:
    old = keyed.retain(OLD, MemoryType.DECISION)
    keyed.retain(FAR, MemoryType.DECISION)
    new, found = _suggest(keyed, NEW)
    (suggestion,) = found
    assert suggestion.ref_id == old and suggestion.similarity == pytest.approx(0.958, abs=0.001)
    assert suggestion.preview == OLD[: keyed.settings.preview_length]  # made as recall's preview is
    assert keyed.get(old, touch=False).superseded_by is None and keyed.get(new, touch=False).supersedes is None


@pytest.mark.parametrize(
    "case",
    ["dedup", "supersedes", "episode", "below threshold"],
)
def test_no_suggestions(keyed: Any, case: str) -> None:
    old = keyed.retain(OLD, MemoryType.DECISION)
    if case == "dedup":
        assert _suggest(keyed, OLD) == (old, [])  # a dedup hit stores nothing new
    elif case == "supersedes":
        other = keyed.retain(FAR, MemoryType.DECISION)
        assert _suggest(keyed, NEW, supersedes=other)[1] == []
    elif case == "episode":
        keyed.retain(OLD, MemoryType.EPISODE)
        assert _suggest(keyed, NEW, MemoryType.EPISODE)[1] == []  # short-term: no suggestions (D2)
    else:
        keyed._settings = keyed.settings.model_copy(update={"supersede_suggest_threshold": 0.99})
        assert _suggest(keyed, NEW)[1] == []


def test_suggestions_follow_scope_and_the_supersede_rule(tmp_path: Path) -> None:
    """Visible to the caller, and allowed by H2's supersede rule: a new private record is offered only records in its
    own scope; a new project record anything the caller can see; never another agent's private record."""
    vectors = {
        "b's note": [1.0, 0.05, 0.0, 0.0],
        "shared note": [1.0, 0.10, 0.0, 0.0],
        "a's note": [1.0, 0.15, 0.0, 0.0],
        "a's new private note": [1.0, 0.30, 0.0, 0.0],
        "a's new shared note": [1.0, 0.30, 0.0, 0.0],
    }
    svc = _service(_settings(tmp_path), KeyedEmbedding(vectors))
    others = svc.retain("b's note", MemoryType.DECISION, scope="agent", caller=B)
    shared = svc.retain("shared note", MemoryType.DECISION)
    mine = svc.retain("a's note", MemoryType.DECISION, scope="agent", caller=A)

    new_private, private = _suggest(svc, "a's new private note", scope="agent", caller=A)
    assert [s.ref_id for s in private] == [mine]
    _, public = _suggest(svc, "a's new shared note", caller=A)
    # a project record may supersede anything a can see, a's two private notes included; b's never
    assert {s.ref_id for s in public} == {new_private, mine, shared} and others not in {s.ref_id for s in public}


def test_the_search_filters_before_taking_three(tmp_path: Path) -> None:
    vectors: dict[str, list[float]] = {NEW: [1.0, 0.0, 0.0, 0.0]}
    for i in range(6):  # six closer records, all another agent's
        vectors[f"hidden {i}"] = [1.0, 0.01 * (i + 1), 0.0, 0.0]
    for i in range(4):  # four eligible, a little further
        vectors[f"shared {i}"] = [1.0, 0.2 + 0.05 * i, 0.0, 0.0]
    svc = _service(_settings(tmp_path), KeyedEmbedding(vectors))
    for i in range(6):
        svc.retain(f"hidden {i}", MemoryType.DECISION, scope="agent", caller=B)
    shared = [svc.retain(f"shared {i}", MemoryType.DECISION) for i in range(4)]
    _, found = _suggest(svc, NEW, caller=A)
    assert [s.ref_id for s in found] == shared[:3]  # at most 3, best first, all eligible

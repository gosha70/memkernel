# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""The core of the wiki identity (memkernel-0-7-wiki-scope S2, S5, S8; SC-4, SC-8)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from memkernel.core.models import AmbiguousDedupError, MemoryType
from tests.unit.test_wiki import _service

if TYPE_CHECKING:
    from memkernel.core.services import MemoryService

pytestmark = pytest.mark.unit

PAGE = "decisions/use-postgres.md"
TEXT = "Use Postgres\n\nBecause of concurrent writes."
A_ID = "11111111-1111-4111-8111-111111111111"
B_ID = "22222222-2222-4222-8222-222222222222"


def _wiki_memory(svc: MemoryService, path_hash: str = "pa", wiki_id: str | None = A_ID, text: str = TEXT) -> str:
    return svc.retain(text, MemoryType.DECISION, source=PAGE, tags=["wiki"], wiki_identity=(path_hash, wiki_id))


@pytest.mark.parametrize("tag", ["wiki-path:abc", "wiki-id:" + A_ID])
def test_retain_refuses_the_reserved_identity_tags(tag: str) -> None:
    svc = _service()
    with pytest.raises(ValueError, match="reserved for the wiki import"):
        svc.retain(TEXT, MemoryType.DECISION, tags=["ci", tag])
    assert svc.count() == 0


def test_wiki_identity_is_written_only_on_a_new_record() -> None:
    svc = _service()
    ref = _wiki_memory(svc)
    memory = svc.get(ref, touch=False)
    assert memory is not None and memory.tags == ["wiki", "wiki-path:pa", f"wiki-id:{A_ID}"]
    hit = svc.retain(
        TEXT,
        MemoryType.DECISION,
        source=PAGE,
        tags=["wiki", "page_sha:x"],
        dedup_source=True,
        dedup_owner=lambda m: f"wiki-id:{A_ID}" in m.tags,
        wiki_identity=("pb", B_ID),  # a dedup hit keeps its identity tags as they are
    )
    assert hit == ref
    memory = svc.get(ref, touch=False)
    assert memory is not None and memory.tags == ["wiki", "wiki-path:pa", f"wiki-id:{A_ID}", "page_sha:x"]


def test_dedup_owner_picks_the_owned_record_among_all_matches() -> None:
    svc = _service()
    other = _wiki_memory(svc, "pb", B_ID)
    mine = _wiki_memory(svc, "pa", A_ID)
    assert other != mine  # identical text at one path in two wikis: two records
    owner = f"wiki-id:{A_ID}"
    hit = svc.retain(TEXT, MemoryType.DECISION, source=PAGE, dedup_source=True, dedup_owner=lambda m: owner in m.tags)
    assert hit == mine


def test_two_owned_dedup_hits_raise_and_write_nothing() -> None:
    svc = _service()
    first, second = _wiki_memory(svc), _wiki_memory(svc)
    with pytest.raises(AmbiguousDedupError) as caught:
        svc.retain(TEXT, MemoryType.DECISION, source=PAGE, dedup_source=True, dedup_owner=lambda m: True)
    assert caught.value.ref_ids == sorted([first, second]) and svc.count() == 2


def test_an_ordinary_retain_never_dedups_onto_a_wiki_memory() -> None:
    """FR-009: the agent's identical text gets its own record; the wiki memory is untouched."""
    svc = _service()
    wiki_ref = _wiki_memory(svc)
    before = svc.get(wiki_ref, touch=False)
    own = svc.retain(TEXT, MemoryType.DECISION, source=PAGE, tags=["ci"])
    assert own != wiki_ref
    after = svc.get(wiki_ref, touch=False)
    assert (
        before is not None and after is not None and after.tags == before.tags and after.session_id == before.session_id
    )
    assert svc.retain(TEXT, MemoryType.DECISION, source=PAGE, tags=["env"]) == own  # the plain record is the hit


def test_set_wiki_identity_changes_only_the_identity_tags() -> None:
    svc = _service()
    ref = _wiki_memory(svc, "old", None)
    before = svc.get(ref, touch=False)
    assert svc.set_wiki_identity(ref, wiki_path="new", wiki_id=A_ID) is True
    after = svc.get(ref, touch=False)
    assert before is not None and after is not None
    assert after.tags == ["wiki", "wiki-path:new", f"wiki-id:{A_ID}"]
    assert after.model_dump(exclude={"tags"}) == before.model_dump(exclude={"tags"})
    assert svc.set_wiki_identity(ref, wiki_path="new", wiki_id=A_ID) is False  # nothing changed


def test_set_wiki_identity_refuses_what_it_must_not_touch() -> None:
    svc = _service()
    with pytest.raises(ValueError, match="not a memory in this store"):
        svc.set_wiki_identity("unknown", wiki_path="p")
    plain = svc.retain("a plain fact", MemoryType.FACT)
    with pytest.raises(ValueError, match="not a wiki memory"):
        svc.set_wiki_identity(plain, wiki_path="p")
    owned = _wiki_memory(svc)
    with pytest.raises(ValueError, match="belongs to wiki"):
        svc.set_wiki_identity(owned, wiki_path="pa", wiki_id=B_ID)  # never moved to another wiki
    memory = svc.get(owned, touch=False)
    assert memory is not None and f"wiki-id:{A_ID}" in memory.tags and f"wiki-id:{B_ID}" not in memory.tags
    other_project = _service()
    with pytest.raises(ValueError, match="not a memory in this store"):
        other_project.set_wiki_identity(owned, wiki_path="pa")


def test_a_promoted_copy_carries_no_wiki_import_tag() -> None:
    svc = _service()
    ref = svc.retain(
        TEXT,
        MemoryType.DECISION,
        source=PAGE,
        tags=["wiki", "page:use-postgres", "page_type:decision", "page_key:k", "page_sha:s", "ops"],
        wiki_identity=("pa", A_ID),
    )
    copy = svc.promote(ref, MemoryType.FACT, content="Postgres is the user DB.", tags=["db"])
    assert copy is not None
    promoted = svc.get(copy, touch=False)
    assert promoted is not None and promoted.tags == ["ops", "db"] and promoted.promoted_from == ref

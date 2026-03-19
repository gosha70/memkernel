"""Unit tests for BM25Index (sparse search)."""

from __future__ import annotations

import pytest

from memkernel.retrieval.sparse import BM25Index


@pytest.mark.unit
def test_add_and_search_returns_document() -> None:
    index = BM25Index()
    index.add("ref1", "the quick brown fox")
    results = index.search("fox", top_k=5)
    assert len(results) == 1
    assert results[0].ref_id == "ref1"
    assert results[0].score > 0


@pytest.mark.unit
def test_multiple_docs_ranked_by_relevance() -> None:
    index = BM25Index()
    index.add("ref_low", "unrelated document about weather and rain")
    index.add("ref_high", "python programming language python code python")
    results = index.search("python", top_k=5)
    ref_ids = [r.ref_id for r in results]
    assert "ref_high" in ref_ids
    assert ref_ids.index("ref_high") < ref_ids.index("ref_low") if "ref_low" in ref_ids else True
    # ref_high must be ranked first
    assert results[0].ref_id == "ref_high"


@pytest.mark.unit
def test_remove_doc_no_longer_returned() -> None:
    index = BM25Index()
    index.add("ref1", "the quick brown fox")
    index.add("ref2", "another document about foxes")
    index.remove("ref1")
    results = index.search("fox", top_k=5)
    ref_ids = [r.ref_id for r in results]
    assert "ref1" not in ref_ids


@pytest.mark.unit
def test_rebuild_reconstructs_index() -> None:
    index = BM25Index()
    index.add("old_ref", "old content that should be gone")
    index.rebuild([("new1", "hello world"), ("new2", "hello python")])
    results = index.search("hello", top_k=5)
    ref_ids = {r.ref_id for r in results}
    assert ref_ids == {"new1", "new2"}
    # old document must not appear
    assert "old_ref" not in ref_ids


@pytest.mark.unit
def test_search_empty_index_returns_empty_list() -> None:
    index = BM25Index()
    assert index.search("anything", top_k=5) == []


@pytest.mark.unit
def test_search_all_returns_all_matching_docs() -> None:
    index = BM25Index()
    for i in range(10):
        index.add(f"ref{i}", f"document about topic_{i % 3} and shared keyword")
    results = index.search_all("shared")
    # All 10 docs contain "shared" — expect all returned
    assert len(results) == 10


@pytest.mark.unit
def test_search_all_excludes_non_matching_docs() -> None:
    index = BM25Index()
    index.add("match", "python snake programming")
    index.add("no_match", "the weather is cloudy today")
    results = index.search_all("python")
    ref_ids = [r.ref_id for r in results]
    assert "match" in ref_ids
    assert "no_match" not in ref_ids


@pytest.mark.unit
def test_needs_rebuild_lifecycle() -> None:
    index = BM25Index()
    # Initially False
    assert index.needs_rebuild is False
    # After mark — True
    index.mark_needs_rebuild()
    assert index.needs_rebuild is True
    # After rebuild — False
    index.rebuild([("r1", "some content")])
    assert index.needs_rebuild is False


@pytest.mark.unit
def test_len_returns_correct_count() -> None:
    index = BM25Index()
    assert len(index) == 0
    index.add("ref1", "first document")
    assert len(index) == 1
    index.add("ref2", "second document")
    assert len(index) == 2
    index.remove("ref1")
    assert len(index) == 1
    index.rebuild([("a", "x"), ("b", "y"), ("c", "z")])
    assert len(index) == 3


@pytest.mark.unit
def test_ranks_are_one_based_and_ascending() -> None:
    index = BM25Index()
    index.add("ref1", "python python python")
    index.add("ref2", "python language")
    results = index.search_all("python")
    assert len(results) >= 1
    for i, result in enumerate(results):
        assert result.rank == i + 1


@pytest.mark.unit
def test_add_same_ref_id_replaces_content() -> None:
    index = BM25Index()
    index.add("ref1", "original content about cats")
    index.add("ref1", "completely different text about dogs")
    assert len(index) == 1
    results = index.search("dogs", top_k=5)
    assert len(results) == 1
    assert results[0].ref_id == "ref1"
    # Should NOT match the old content
    cat_results = index.search("cats", top_k=5)
    assert len(cat_results) == 0

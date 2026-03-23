"""Unit tests for eval/run_eval.py compute_metrics alias-collapse logic.

These tests exercise the logical-memory scoring fix: a chunk ref_id that is
an alias of a canonical ref_id must score as a hit for that memory, and
returning multiple aliases of the same memory must not inflate recall/precision.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

# eval/ is at project root — add it to sys.path if not already present.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from eval.run_eval import compute_metrics  # noqa: E402
from memkernel.core.models import ArtifactRef, MemoryType  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _ref(ref_id: str) -> ArtifactRef:
    return ArtifactRef(
        ref_id=ref_id,
        preview="preview",
        score=1.0,
        token_count=10,
        type=MemoryType.CODE,
        timestamp=_NOW,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_chunk_hit_scores_as_full_recall() -> None:
    """Retrieving a chunk ref counts as a hit for the logical memory (recall=1.0)."""
    id_map = {"m01": {"ref_canon", "ref_chunk1", "ref_chunk2"}}
    queries = [{"id": "q01", "query": "anything", "relevant_ids": ["m01"]}]
    refs_by_query = {"q01": [_ref("ref_chunk1")]}

    metrics = compute_metrics(queries, id_map, refs_by_query, top_k=5)

    assert metrics["recall_at_k"] == 1.0
    assert metrics["mrr"] == 1.0


@pytest.mark.unit
def test_two_aliases_same_memory_count_as_one_hit() -> None:
    """Returning canonical + chunk of the same memory yields hits=1, not hits=2."""
    id_map = {"m01": {"ref_canon", "ref_chunk"}}
    queries = [{"id": "q01", "query": "anything", "relevant_ids": ["m01"]}]
    # Both aliases returned; top_k=2
    refs_by_query = {"q01": [_ref("ref_canon"), _ref("ref_chunk")]}

    metrics = compute_metrics(queries, id_map, refs_by_query, top_k=2)

    # One logical hit out of top_k=2 retrieved slots
    assert metrics["recall_at_k"] == 1.0
    assert metrics["precision_at_k"] == pytest.approx(0.5)
    assert metrics["mrr"] == 1.0


@pytest.mark.unit
def test_irrelevant_ref_scores_zero() -> None:
    """A retrieved ref_id that maps to no relevant dataset_id scores as a miss."""
    id_map = {"m01": {"ref_canon"}}
    queries = [{"id": "q01", "query": "anything", "relevant_ids": ["m01"]}]
    refs_by_query = {"q01": [_ref("ref_other")]}

    metrics = compute_metrics(queries, id_map, refs_by_query, top_k=5)

    assert metrics["recall_at_k"] == 0.0
    assert metrics["mrr"] == 0.0


@pytest.mark.unit
def test_mrr_uses_rank_of_first_alias_hit() -> None:
    """MRR is based on the rank of the first correct alias in the result list."""
    id_map = {"m01": {"ref_canon", "ref_chunk"}}
    queries = [{"id": "q01", "query": "anything", "relevant_ids": ["m01"]}]
    # ref_chunk is the third result (after two irrelevant refs)
    refs_by_query = {"q01": [_ref("ref_a"), _ref("ref_b"), _ref("ref_chunk")]}

    metrics = compute_metrics(queries, id_map, refs_by_query, top_k=5)

    assert metrics["mrr"] == pytest.approx(1.0 / 3)

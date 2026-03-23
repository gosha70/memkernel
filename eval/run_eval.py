"""Retrieval evaluation harness for MemKernel.

Runs recall@k, precision@k, and MRR for three search modes:
  dense   — ChromaDB vector similarity only
  sparse  — BM25 only
  hybrid  — Dense + BM25 fused via RRF (default production mode)

Usage (from project root):
    poetry run python eval/run_eval.py
    poetry run python eval/run_eval.py --mode hybrid --top-k 5
    poetry run python eval/run_eval.py --dataset eval/datasets/memkernel_eval.json --mode all
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Bootstrap: ensure src/ is on the path when run as a standalone script.
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_SRC = _PROJECT_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import chromadb  # noqa: E402 — after sys.path fixup

from memkernel.config import MemKernelSettings  # noqa: E402
from memkernel.core.models import ArtifactRef, MemoryType, SearchQuery  # noqa: E402
from memkernel.core.services import MemoryService  # noqa: E402
from memkernel.retrieval.chunking import ASTChunker  # noqa: E402
from memkernel.retrieval.embeddings import SentenceTransformerEmbedding  # noqa: E402
from memkernel.retrieval.search import (  # noqa: E402
    HybridSearchService,
    build_artifact_refs,
    filter_sparse_results,
    rrf_fuse,
)
from memkernel.retrieval.sparse import BM25Index  # noqa: E402
from memkernel.storage.chroma import ChromaVectorStore  # noqa: E402

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

EvalMemory = dict[str, str]  # id, content, type, source
EvalQuery = dict[str, Any]  # id, query, relevant_ids
Dataset = dict[str, Any]  # memories, queries


# ---------------------------------------------------------------------------
# Dataset loader
# ---------------------------------------------------------------------------


def load_dataset(path: str | Path) -> Dataset:
    """Load and minimally validate the evaluation dataset JSON."""
    with open(path, encoding="utf-8") as fh:
        data: Dataset = json.load(fh)

    if "memories" not in data or "queries" not in data:
        raise ValueError("Dataset JSON must have 'memories' and 'queries' keys")

    for mem in data["memories"]:
        for key in ("id", "content", "type"):
            if key not in mem:
                raise ValueError(f"Memory entry missing required key '{key}': {mem}")

    for qry in data["queries"]:
        for key in ("id", "query", "relevant_ids"):
            if key not in qry:
                raise ValueError(f"Query entry missing required key '{key}': {qry}")

    return data


# ---------------------------------------------------------------------------
# Service bootstrap
# ---------------------------------------------------------------------------


def build_service(
    project_id: str = "eval",
) -> tuple[
    MemoryService, ChromaVectorStore, BM25Index, SentenceTransformerEmbedding, HybridSearchService, MemKernelSettings
]:
    """Construct a MemoryService backed by an in-memory (ephemeral) ChromaDB."""
    settings = MemKernelSettings(project_id=project_id, chroma_persist_path="")
    client = chromadb.EphemeralClient()
    store = ChromaVectorStore(settings, client=client)
    embedding = SentenceTransformerEmbedding(settings)
    sparse = BM25Index()
    search_svc = HybridSearchService(store, embedding, sparse, settings)
    svc = MemoryService(
        store,
        embedding,
        sparse,
        search_svc,
        settings,
        chunker=ASTChunker(settings),
    )
    return svc, store, sparse, embedding, search_svc, settings


# ---------------------------------------------------------------------------
# Seeding
# ---------------------------------------------------------------------------


def seed_memories(
    svc: MemoryService,
    memories: list[EvalMemory],
) -> dict[str, set[str]]:
    """Retain all dataset memories and return a mapping of dataset-id -> all valid ref_ids.

    For code memories, chunk ref_ids are included alongside the canonical ref_id
    because recall may rank a chunk ref ahead of the canonical — a chunk hit is
    also a correct retrieval.
    """
    id_map: dict[str, set[str]] = {}
    for mem in memories:
        ref_id = svc.retain(
            content=mem["content"],
            type=MemoryType(mem["type"]),
            source=mem.get("source", ""),
        )
        valid_ids: set[str] = {ref_id}
        canonical = svc.get(ref_id)
        if canonical is not None and canonical.chunk_refs:
            valid_ids.update(canonical.chunk_refs)
        id_map[mem["id"]] = valid_ids
    return id_map


# ---------------------------------------------------------------------------
# Metric computation
# ---------------------------------------------------------------------------


def compute_metrics(
    queries: list[EvalQuery],
    id_map: dict[str, set[str]],
    refs_by_query: dict[str, list[ArtifactRef]],
    top_k: int,
) -> dict[str, float]:
    """Compute recall@k, precision@k, and MRR across all queries.

    Args:
        queries:        List of query dicts with 'id' and 'relevant_ids'.
        id_map:         Mapping from dataset memory id -> all valid ref_ids
                        (canonical + chunk refs for code memories).
        refs_by_query:  Mapping from query id -> list of returned ArtifactRefs.
        top_k:          Cutoff for precision/recall/MRR.

    Returns:
        Dict with keys 'recall_at_k', 'precision_at_k', 'mrr'.

    Scoring is at the *logical memory* level: canonical and chunk ref_ids for the
    same dataset entry are aliases. Retrieving any alias counts as one hit for that
    memory, and the recall denominator is the number of distinct relevant memories
    (not the number of aliases).
    """
    # Build a reverse map: any ref_id (canonical or chunk) -> dataset_id.
    ref_to_dataset: dict[str, str] = {}
    for did, ref_ids in id_map.items():
        for ref_id in ref_ids:
            ref_to_dataset[ref_id] = did

    recall_scores: list[float] = []
    precision_scores: list[float] = []
    rr_scores: list[float] = []

    for qry in queries:
        qid: str = qry["id"]
        relevant_dataset_ids: set[str] = {did for did in qry["relevant_ids"] if did in id_map}

        # Resolve each retrieved ref_id to its dataset_id, preserving the
        # original rank (1-based position in the full result list) and
        # deduplicating so that multiple aliases of the same memory count as
        # one hit.  Unmapped refs are skipped for recall/precision but their
        # positions still count against rank for MRR purposes.
        retrieved_ordered: list[tuple[int, str]] = []  # (original_rank, dataset_id)
        seen: set[str] = set()
        for rank, ref in enumerate(refs_by_query.get(qid, [])[:top_k], start=1):
            dataset_id = ref_to_dataset.get(ref.ref_id)
            if dataset_id is not None and dataset_id not in seen:
                retrieved_ordered.append((rank, dataset_id))
                seen.add(dataset_id)

        retrieved_set = {did for _, did in retrieved_ordered}
        hits = len(retrieved_set & relevant_dataset_ids)
        recall_scores.append(hits / len(relevant_dataset_ids) if relevant_dataset_ids else 0.0)
        precision_scores.append(hits / top_k if top_k > 0 else 0.0)

        rr: float = 0.0
        for rank, did in retrieved_ordered:
            if did in relevant_dataset_ids:
                rr = 1.0 / rank
                break
        rr_scores.append(rr)

    n = len(queries)
    return {
        "recall_at_k": sum(recall_scores) / n if n else 0.0,
        "precision_at_k": sum(precision_scores) / n if n else 0.0,
        "mrr": sum(rr_scores) / n if n else 0.0,
    }


# ---------------------------------------------------------------------------
# Per-mode search
# ---------------------------------------------------------------------------


def run_dense(
    queries: list[EvalQuery],
    store: ChromaVectorStore,
    embedding: SentenceTransformerEmbedding,
    settings: MemKernelSettings,
    top_k: int,
) -> dict[str, list[ArtifactRef]]:
    """Dense-only search: vector similarity via ChromaDB."""
    results: dict[str, list[ArtifactRef]] = {}
    over_fetch = max(1, top_k * 3)
    for qry in queries:
        query_emb = embedding.embed([qry["query"]])[0]
        dense_results = store.search_dense(query_emb, over_fetch)
        fused = rrf_fuse(settings.rrf_k, dense_results)
        refs = build_artifact_refs(fused, top_k, store, settings.preview_length)
        results[qry["id"]] = refs
    return results


def run_sparse(
    queries: list[EvalQuery],
    store: ChromaVectorStore,
    sparse: BM25Index,
    settings: MemKernelSettings,
    top_k: int,
) -> dict[str, list[ArtifactRef]]:
    """Sparse-only search: BM25 index with post-filtering."""
    results: dict[str, list[ArtifactRef]] = {}
    over_fetch = max(1, top_k * 3)
    for qry in queries:
        sparse_all = sparse.search_all(qry["query"])
        filtered = filter_sparse_results(sparse_all, None, store)[:over_fetch]
        fused = rrf_fuse(settings.rrf_k, filtered)
        refs = build_artifact_refs(fused, top_k, store, settings.preview_length)
        results[qry["id"]] = refs
    return results


def run_hybrid(
    queries: list[EvalQuery],
    search_svc: HybridSearchService,
    top_k: int,
) -> dict[str, list[ArtifactRef]]:
    """Hybrid search: dense + sparse fused via RRF."""
    results: dict[str, list[ArtifactRef]] = {}
    for qry in queries:
        sq = SearchQuery(query_text=qry["query"], top_k=top_k)
        refs = search_svc.search(sq)
        results[qry["id"]] = refs
    return results


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------

_THRESHOLD_RECALL = 0.7
_THRESHOLD_MRR = 0.5

_MODE_LABELS: dict[str, str] = {
    "dense": "Dense (vector only)",
    "sparse": "Sparse (BM25 only)",
    "hybrid": "Hybrid (RRF fusion)",
}


def _print_results(mode: str, metrics: dict[str, float], top_k: int) -> None:
    label = _MODE_LABELS.get(mode, mode)
    print(f"\n{'=' * 60}")
    print(f"  Mode: {label}   top_k={top_k}")
    print(f"{'=' * 60}")
    print(f"  recall@{top_k}    : {metrics['recall_at_k']:.4f}")
    print(f"  precision@{top_k}  : {metrics['precision_at_k']:.4f}")
    print(f"  MRR          : {metrics['mrr']:.4f}")

    if mode == "hybrid":
        print()
        recall_ok = metrics["recall_at_k"] >= _THRESHOLD_RECALL
        mrr_ok = metrics["mrr"] >= _THRESHOLD_MRR
        print(f"  recall@{top_k} >= {_THRESHOLD_RECALL}: {'PASS' if recall_ok else 'FAIL'}")
        print(f"  MRR >= {_THRESHOLD_MRR}:         {'PASS' if mrr_ok else 'FAIL'}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="MemKernel retrieval evaluation harness")
    parser.add_argument(
        "--mode",
        choices=["dense", "sparse", "hybrid", "all"],
        default="all",
        help="Search mode to evaluate (default: all)",
    )
    parser.add_argument(
        "--dataset",
        default=str(_PROJECT_ROOT / "eval" / "datasets" / "memkernel_eval.json"),
        help="Path to the evaluation dataset JSON",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=5,
        help="Number of results to retrieve per query (default: 5)",
    )
    args = parser.parse_args()

    top_k: int = args.top_k
    modes: list[str] = ["dense", "sparse", "hybrid"] if args.mode == "all" else [args.mode]

    print(f"Loading dataset from {args.dataset} ...")
    dataset = load_dataset(args.dataset)
    memories: list[EvalMemory] = dataset["memories"]
    queries: list[EvalQuery] = dataset["queries"]
    print(f"  {len(memories)} memories, {len(queries)} queries")

    print("\nBuilding service and loading embedding model (this may take a minute) ...")
    svc, store, sparse, embedding, search_svc, settings = build_service()

    print("Seeding memories ...")
    id_map = seed_memories(svc, memories)
    print(f"  Seeded {len(id_map)} memories")

    hybrid_passed = True

    for mode in modes:
        if mode == "dense":
            refs_by_query = run_dense(queries, store, embedding, settings, top_k)
        elif mode == "sparse":
            refs_by_query = run_sparse(queries, store, sparse, settings, top_k)
        else:
            refs_by_query = run_hybrid(queries, search_svc, top_k)

        metrics = compute_metrics(queries, id_map, refs_by_query, top_k)
        _print_results(mode, metrics, top_k)

        if mode == "hybrid":
            recall_ok = metrics["recall_at_k"] >= _THRESHOLD_RECALL
            mrr_ok = metrics["mrr"] >= _THRESHOLD_MRR
            hybrid_passed = recall_ok and mrr_ok

    print()
    if "hybrid" in modes:
        sys.exit(0 if hybrid_passed else 1)


if __name__ == "__main__":
    main()

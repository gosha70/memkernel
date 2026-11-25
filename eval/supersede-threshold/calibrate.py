# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""Calibrate the supersede-suggestion threshold (specs/memkernel-0-17-supersede-and-canonical-hash, D3).

Embeds each labelled pair in ``tests/fixtures/supersede/pairs.json`` with the configured embedding model (the default,
``all-MiniLM-L6-v2``, unless ``MEMKERNEL_EMBEDDING_MODEL`` says otherwise) and takes their cosine similarity, as
``recall``'s dense search scores a hit (1 - cosine distance). The rule (D3, as the owner set it): find the lowest
threshold, in steps of 0.01 from 0.50 to 0.99, at which at most ``MAX_DIFFERENT`` of the different pairs would be
suggested; the default is the **highest** threshold that catches as many version pairs as that lowest one, with at most
``MAX_DIFFERENT`` different pairs suggested. If the lowest one catches fewer than ``MIN_VERSIONS`` of the version pairs,
no default is chosen: the numbers go to the owner.

Usage:
    poetry run python eval/supersede-threshold/calibrate.py [--json calibration.json]
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "src"))

from memkernel.config import MemKernelSettings  # noqa: E402

PAIRS = HERE.parents[1] / "tests" / "fixtures" / "supersede" / "pairs.json"
VERSION, DIFFERENT = "version", "different"
LOWEST, HIGHEST, STEP_HUNDREDTHS = 50, 99, 1  # thresholds 0.50 … 0.99 in hundredths
MAX_DIFFERENT = 1  # at most this many different pairs suggested at the chosen threshold
MIN_VERSIONS = 24  # of 30: below this the build stops and asks the owner (D3)


@dataclass
class Calibration:
    model: str
    threshold: float | None  # None: no threshold in range meets the rule, or too few versions caught
    versions_caught: int
    versions: int
    different_suggested: int
    different: int
    passes: bool


def cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity, which is what ``search_dense`` scores (1 - cosine distance)."""
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    return dot / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)))


def _counts(similarities: list[tuple[str, float]], threshold: float) -> tuple[int, int]:
    """(version pairs caught, different pairs suggested) at ``threshold``."""
    caught = sum(s >= threshold for kind, s in similarities if kind == VERSION)
    suggested = sum(s >= threshold for kind, s in similarities if kind == DIFFERENT)
    return caught, suggested


def table(similarities: list[tuple[str, float]]) -> list[tuple[float, int, int]]:
    """(threshold, version pairs caught, different pairs suggested) for every threshold the rule considers."""
    return [(h / 100, *_counts(similarities, h / 100)) for h in range(LOWEST, HIGHEST + 1, STEP_HUNDREDTHS)]


def choose(similarities: list[tuple[str, float]], model: str) -> Calibration:
    """Apply D3's rule to ``(kind, similarity)`` pairs."""
    versions = sum(kind == VERSION for kind, _ in similarities)
    different = sum(kind == DIFFERENT for kind, _ in similarities)
    rows = table(similarities)
    lowest = next(((t, c, d) for t, c, d in rows if d <= MAX_DIFFERENT), None)
    if lowest is None:
        return Calibration(model, None, 0, versions, different, different, False)
    _, caught, _ = lowest
    if caught < MIN_VERSIONS:
        return Calibration(model, None, caught, versions, lowest[2], different, False)
    threshold, caught, suggested = max(
        (row for row in rows if row[0] >= lowest[0] and row[1] == caught and row[2] <= MAX_DIFFERENT),
        key=lambda row: row[0],
    )
    return Calibration(model, threshold, caught, versions, suggested, different, True)


def similarities(pairs: list[dict[str, str]], embed: Any) -> list[tuple[str, str, float]]:
    """``(kind, type, similarity)`` for each pair, embedding all texts in one batch."""
    vectors = embed([text for p in pairs for text in (p["a"], p["b"])])
    return [(p["kind"], p["type"], cosine(vectors[2 * i], vectors[2 * i + 1])) for i, p in enumerate(pairs)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("--json", type=Path, help="also write the result and every pair's similarity as JSON")
    args = parser.parse_args(argv)
    from memkernel.retrieval.embeddings import SentenceTransformerEmbedding

    settings = MemKernelSettings()
    pairs = json.loads(PAIRS.read_text(encoding="utf-8"))["pairs"]
    rows = similarities(pairs, SentenceTransformerEmbedding(settings).embed)
    pairs_only = [(kind, s) for kind, _, s in rows]
    result = choose(pairs_only, settings.embedding_model)
    for kind in (VERSION, DIFFERENT):
        scores = sorted(s for k, _, s in rows if k == kind)
        print(
            f"{kind:9} n={len(scores)}  min {scores[0]:.3f}  "
            f"median {scores[len(scores) // 2]:.3f}  max {scores[-1]:.3f}"
        )
    print(
        f"model {result.model}: threshold {result.threshold}, versions caught {result.versions_caught}/"
        f"{result.versions}, different suggested {result.different_suggested}/{result.different}, "
        f"{'passes' if result.passes else 'FAILS: bring the numbers to the owner'}"
    )
    if args.json:
        payload = {
            **asdict(result),
            "table": [
                {"threshold": t, "versions_caught": c, "different_suggested": d} for t, c, d in table(pairs_only)
            ],
            "pairs": [{"kind": k, "type": t, "similarity": round(s, 4)} for k, t, s in rows],
        }
        args.json.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return 0 if result.passes else 1


if __name__ == "__main__":
    raise SystemExit(main())

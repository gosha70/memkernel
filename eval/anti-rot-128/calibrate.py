# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""Calibrate a hook relevance floor (memkernel-0-11-anti-rot-injection FR-006, D5), and keep the evidence.

The floor was dropped after this run (spec amendment A5): it calibrated to 0.20, changed no checkpoint-shaped block,
and off-topic checkpoints scored as high as the needed records. The runner stays so the evidence can be reproduced:
it computes similarities with the store's own embedder and simulates the floor as the dropped selector did (the
candidate window filtered by the floor, then the real ``_distinct()`` to five), beside the real hook blocks.

Runs the #57 corpus's crowded store (code-copilot-team 00d49c0, the embedding pinned at revision 1110a243) through
the complete hook paths, compact recovery and ``on_post_compact()``, with each case's later task inside a
checkpoint-shaped query and as the bare line. For each case and path it records the similarities of the case's
required targets (the #57 runner's ``judge()``), then picks the floor from the checkpoint-shaped run: the lowest
required-target similarity minus 0.05, rounded down to two decimals. It then runs both blocks at that floor and
judges the five memories each displays. Three failures are counted apart: a required target missing from the
ten-candidate window, removed by the floor, or removed or misordered in the final five. Any failure, or a floor not
above zero, fails calibration: the default stays unset (None).

Usage: poetry run python eval/anti-rot-128/calibrate.py [--cct <code-copilot-team checkout>] [--out <file>]
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import re
import subprocess
import sys
import tempfile
from importlib import metadata
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "src"))

from memkernel import lifecycle as lifecycle_module  # noqa: E402
from memkernel.core.models import MemoryTier, MemoryType  # noqa: E402
from memkernel.lifecycle import MemoryLifecycle  # noqa: E402

MARGIN = 0.05
CONFIG_TRAP = "Config redaction is not free-text redaction"
CONFIG_RIGHT = "Trace archive reuses the ingest redaction path"
TEMPLATE = (
    "SESSION CHECKPOINT\nDone: read the code involved.\nCurrent: {task}\nNext: implement it and run the tests.\n"
    "Open: none."
)
SHAPES = ("checkpoint", "bare")
# Work unrelated to the corpus (a sanity check of the floor's separation, asked for on #131's build): each goes
# through both hook paths, without a floor, and the top similarities per block are recorded.
OFF_TOPIC = (
    "Fix the CSS grid so the recipe cards wrap on narrow phone screens in the bakery storefront.",
    "Tune the PID gains so the drone holds altitude in gusty wind without oscillating.",
    "Reconcile the quarterly sales spreadsheet: the VLOOKUP returns #N/A for renamed product codes.",
    "Add a dark mode toggle to the iOS weather app and persist the choice in UserDefaults.",
    "Clean the survey dataset: drop duplicate respondents and impute missing ages by region median.",
)
PATHS = ("compact-recovery", "post-compact")
_REF = re.compile(r"\(([0-9a-f-]{36})\)$")


def _load_57() -> Any:
    spec = importlib.util.spec_from_file_location("decisions57_run", ROOT / "eval" / "decisions-57" / "run.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def similarities(svc: Any, query: str, memories: list[Any]) -> list[float]:
    """Each memory's cosine similarity to ``query``, with the store's embedder (as the dropped selector scored)."""
    vectors = svc._embedding.embed([query, *(m.content for m in memories)])
    return [_cosine(vectors[0], vector) for vector in vectors[1:]]


def _cosine(a: list[float], b: list[float]) -> float:
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return sum(x * y for x, y in zip(a, b, strict=True)) / norm if norm else 0.0


def simulated(cand: list[Any], sims: list[float], checkpoint: Any, floor: float | None) -> list[Any]:
    """The five memories a block would show at ``floor``: the window filtered, then the real ``_distinct()``."""
    kept = [m for m, s in zip(cand, sims, strict=True) if floor is None or s >= floor]
    return lifecycle_module._distinct(kept, checkpoint, lifecycle_module.POST_COMPACT_CONTEXT_TOP_K)


def targets(record: dict[str, Any], successors: dict[str, str]) -> list[str]:
    """The names the #57 judgement requires displayed for this case."""
    if record["kind"] == "stale":
        return [successors[record["title"]]]
    if record["kind"] == "conflict":
        return [record["title"], record["partner"].rstrip(".")]
    if record["title"] == CONFIG_TRAP:
        return [CONFIG_RIGHT]
    return [record["title"]]


def judge(record: dict[str, Any], shown: list[str], successors: dict[str, str]) -> bool:
    """The #57 runner's complete conditions, on the names displayed, in order."""
    if record["kind"] == "stale":
        return successors[record["title"]] in shown and record["title"] not in shown
    if record["title"] == CONFIG_TRAP:
        if CONFIG_RIGHT not in shown:
            return False
        return CONFIG_TRAP not in shown or shown.index(CONFIG_RIGHT) < shown.index(CONFIG_TRAP)
    return all(name in shown for name in targets(record, successors))


def displayed(text: str, names: dict[str, str]) -> list[str]:
    """The memories a block's context section shows, in order, by name."""
    section = text.split(lifecycle_module.HEADING_CONTEXT, 1)[1].split("\n###", 1)[0].split("\n---", 1)[0]
    shown = []
    for line in section.splitlines():
        found = _REF.search(line.strip())
        if line.startswith("- [") and found:
            shown.append(names.get(found.group(1), found.group(1)))
    return shown


def run_block(lifecycle: MemoryLifecycle, path: str) -> str:
    return lifecycle._compact_recovery("") if path == "compact-recovery" else lifecycle.on_post_compact()


def window(svc: Any, query: str) -> list[Any]:
    refs = svc.recall(query, tier=MemoryTier.LONG_TERM, top_k=lifecycle_module.HOOK_CANDIDATES, touch=False)
    return [m for m in (svc.get(r.ref_id, touch=False) for r in refs) if m is not None]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cct", default=str(Path.home() / "dev" / "repo" / "code-copilot-team"))
    parser.add_argument("--out", default=str(HERE / "calibration.json"))
    args = parser.parse_args()
    r57 = _load_57()
    records = r57.parse_corpus(r57.CORPUS.read_text(encoding="utf-8"))
    cct = Path(args.cct)
    cct_commit = r57._git(cct, "rev-parse", "--verify", f"{r57.CCT_REV}^{{commit}}").strip()
    extra = r57.cct_distractors(cct, cct_commit, records)
    model = r57.embedding_snapshot()
    report: dict[str, Any] = {
        "embedding_model": r57.EMBEDDING_MODEL,
        "embedding_revision": r57.EMBEDDING_REVISION,
        "versions": {name: metadata.version(name) for name in ("sentence-transformers", "chromadb", "torch")},
        "cct_commit": cct_commit,
        "runner_commit": subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip(),
        "margin": MARGIN,
        "template": TEMPLATE,
    }
    with tempfile.TemporaryDirectory() as tmp:
        svc = r57.service(Path(tmp), model)
        refs = r57.seed(svc, records, superseded=True, extra=extra)
        names = {ref: name for name, ref in refs.items()}
        life = MemoryLifecycle(svc, svc.settings)

        def probe(query: str) -> tuple[Any, list[Any], list[float], dict[str, list[str]]]:
            checkpoint_ref = svc.retain(query, MemoryType.EPISODE, checkpoint=True)  # the newest checkpoint
            checkpoint = svc.get(checkpoint_ref, touch=False)
            cand = window(svc, query)
            sims = similarities(svc, query, cand)
            real = {path: displayed(run_block(life, path), names) for path in PATHS}
            return checkpoint, cand, sims, real

        cases: list[dict[str, Any]] = []
        for record in records:
            for shape in SHAPES:
                task = record["replay"]["later-task"]
                query = TEMPLATE.format(task=task) if shape == "checkpoint" else task
                checkpoint, cand, sims, real = probe(query)
                cases.append(
                    {
                        "title": record["title"],
                        "kind": record["kind"],
                        "shape": shape,
                        "query": query,
                        "targets": targets(record, r57.SUCCESSORS),
                        "window": {names.get(m.ref_id, m.ref_id): s for m, s in zip(cand, sims, strict=True)},
                        "real_blocks": {
                            p: {"displayed": d, "judged": judge(record, d, r57.SUCCESSORS)} for p, d in real.items()
                        },
                        "_record": record,
                        "_probe": (checkpoint, cand, sims),
                    }
                )
        checkpoint_cases = [c for c in cases if c["shape"] == "checkpoint"]
        for case in cases:
            case["missing_from_window"] = [n for n in case["targets"] if n not in case["window"]]
        target_sims = [c["window"][n] for c in checkpoint_cases for n in c["targets"] if n in c["window"]]
        floor = math.floor((min(target_sims) - MARGIN) * 100) / 100 if target_sims else None
        report["lowest_target_similarity"] = min(target_sims) if target_sims else None
        report["candidate_floor"] = floor
        window_misses = floor_removed = final_failures = 0
        for case in cases:
            record = case.pop("_record")
            checkpoint, cand, sims = case.pop("_probe")
            shown = [names.get(m.ref_id, m.ref_id) for m in simulated(cand, sims, checkpoint, floor)]
            case["removed_by_floor"] = [
                n for n in case["targets"] if floor is not None and n in case["window"] and case["window"][n] < floor
            ]
            case["distractors_passing"] = sum(
                1 for n, s in case["window"].items() if n not in case["targets"] and floor is not None and s >= floor
            )
            no_floor = [names.get(m.ref_id, m.ref_id) for m in simulated(cand, sims, checkpoint, None)]
            case["at_floor"] = {
                "displayed": shown,
                "judged": judge(record, shown, r57.SUCCESSORS),
                "abstained": not shown,
                "changed_by_floor": shown != no_floor,
            }
            if case["shape"] == "checkpoint":
                window_misses += len(case["missing_from_window"])
                floor_removed += len(case["removed_by_floor"])
                final_failures += sum(1 for _ in PATHS if not case["at_floor"]["judged"])
        report["failures"] = {
            "missing_from_window": window_misses,
            "removed_by_floor": floor_removed,
            "final_five": final_failures,
        }
        failed = window_misses or floor_removed or final_failures or floor is None or floor <= 0
        report["calibrated_floor"] = None if failed else floor
        report["calibration_failed"] = bool(failed)
        report["cases"] = cases
        off_topic = []
        for task in OFF_TOPIC:
            checkpoint, cand, sims, real = probe(TEMPLATE.format(task=task))
            by_name = {names.get(m.ref_id, m.ref_id): s for m, s in zip(cand, sims, strict=True)}
            off_topic.append(
                {
                    "task": task,
                    "window_top": [round(s, 3) for s in sorted(sims, reverse=True)[:5]],
                    "displayed": {
                        p: sorted((round(by_name[n], 3) for n in d if n in by_name), reverse=True)
                        for p, d in real.items()
                    },
                }
            )
        report["off_topic"] = off_topic
    Path(args.out).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"lowest target similarity {report['lowest_target_similarity']}, candidate floor {floor}")
    print(f"failures {report['failures']}; calibrated floor {report['calibrated_floor']}")
    changed = sum(1 for c in checkpoint_cases if c["at_floor"]["changed_by_floor"])
    print(f"checkpoint-shaped cases changed by the floor: {changed}/{len(checkpoint_cases)}")
    for o in report["off_topic"]:
        print(f"  off-topic {o['task'][:50]:<50} window top {o['window_top'][:3]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

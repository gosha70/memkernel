# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""Replay the #57 decision corpus against unchanged memkernel (research note, recommendation step 2).

Seeds the 12 CCT decision records (``corpus.md``) and memkernel's own ADRs as unrelated decisions into a fresh
store, then runs each record's later task as the template's recall query (``type="decision"``, ``top_k=5``).
Stale cases run twice: as an agent would have left them (never superseded) and with ``supersedes=`` set. A last
probe checks whether a decision whose cited file changes is ever flagged, next to a ``code`` memory as control.

Usage: poetry run python eval/decisions-57/run.py [--top-k 5] [--cct <code-copilot-team checkout>] [--cct-rev <commit>]
       [--out <file>]
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

import chromadb  # noqa: E402

from memkernel import __version__  # noqa: E402
from memkernel.config import MemKernelSettings  # noqa: E402
from memkernel.core.models import MemoryType  # noqa: E402
from memkernel.factory import build_service  # noqa: E402

HERE = Path(__file__).resolve().parent
CORPUS = HERE / "corpus.md"
CCT_REV = "00d49c0a9eb51e9bf234cee70490889b151cd550"  # code-copilot-team commit of the published results
TOP_K = 5  # the template's recall-before-building query; results-k3.json is the run that changed it from 3
SUCCESSORS = {
    "Benchmark UI was backend-free, one-shot and Studio-only": "(successor) benchmark step",
    "merge.require_green_ci was never read": "(successor) green-CI correction",
}
RECORD_FIELDS = ("decision", "requirement", "chosen", "rejected", "evidence", "revisit-when")
# The require_green_ci record's successor is not in the corpus; this is its correction, as the record's evidence
# describes it (code-copilot-team@e39969f specs/auto-build-loop-merge-profile/spec.md:Correction).
GREEN_CI_CORRECTION = (
    "decision: In the context of the merge profile, we chose GitHub branch protection as the only green-CI gate "
    "over the merge.require_green_ci key, because the driver never read the key and it has been removed.\n"
    "requirement: autonomous merge gated on green CI.\n"
    "chosen: GitHub branch protection; the driver arms auto-merge.\n"
    "rejected: merge.require_green_ci: never read by the driver, removed.\n"
    "evidence: code-copilot-team@e39969f specs/auto-build-loop-merge-profile/spec.md:Correction; issue: #80.\n"
    "revisit-when: a driver-side CI gate is reintroduced."
)


def parse_corpus(text: str) -> list[dict[str, Any]]:
    records = []
    for block in re.split(r"^### ", text.split("## Final summary")[0], flags=re.MULTILINE)[1:]:
        heading, _, body = block.partition("\n")
        kind, _, title = heading.partition(": ")
        fields = dict(re.findall(r"^([a-z-]+): (.*)$", body, flags=re.MULTILINE))
        replay = dict(re.findall(r"^  ([a-z-]+): (.*)$", body, flags=re.MULTILINE))
        content = "\n".join(f"{name}: {fields[name]}" for name in RECORD_FIELDS)
        records.append(
            {
                "kind": kind,
                "title": title.strip(),
                "content": content,
                "partner": fields.get("partner", ""),
                "replay": replay,
                "first_line": len(f"decision: {fields['decision']}"),
            }
        )
    return records


def service(tmp: Path) -> Any:
    settings = MemKernelSettings(
        project_id="decisions57",
        project_root=str(tmp),
        state_dir=str(tmp / "state"),
        chroma_persist_path=str(tmp / "chroma"),
    )
    return build_service(settings, chroma_client=chromadb.EphemeralClient())


def _git(cct: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(cct), *args], capture_output=True, text=True, check=True).stdout


def cct_distractors(cct: Path, rev: str, records: list[dict[str, Any]]) -> list[tuple[str, str]]:
    """The opening of each CCT spec at ``rev``, read from git (never the working tree); cited specs are left out.

    These are spec excerpts stored as decisions: same-domain noise, not independently recorded decisions.
    """
    cited = set(re.findall(r"specs/([\w.-]+)/", "\n".join(r["content"] for r in records)))
    paths = [
        p
        for p in _git(cct, "ls-tree", "-r", "--name-only", rev, "--", "specs").splitlines()
        if re.fullmatch(r"specs/[^/]+/spec\.md", p)
    ]
    out = [
        (f"cct-spec:{Path(p).parent.name}", _git(cct, "show", f"{rev}:{p}")[:1500])
        for p in sorted(paths)
        if Path(p).parent.name not in cited
    ]
    if not out:
        raise SystemExit(f"no code-copilot-team specs at {rev} in {cct}; pass --cct <checkout>")
    return out


def seed(svc: Any, records: list[dict[str, Any]], superseded: bool, extra: list[tuple[str, str]]) -> dict[str, str]:
    refs = {r["title"]: svc.retain(r["content"], MemoryType.DECISION) for r in records}
    for name, text in extra:
        refs[name] = svc.retain(text, MemoryType.DECISION)
    for adr in sorted((ROOT / "docs" / "adr").glob("ADR-*.md")):
        refs[adr.stem] = svc.retain(
            adr.read_text(encoding="utf-8")[:1500], MemoryType.DECISION, source=f"docs/adr/{adr.name}"
        )
    if superseded:
        ui = refs["Benchmark UI was backend-free, one-shot and Studio-only"]
        step = next(r for r in records if r["title"] == "Benchmark step reuses the one correlate scan seam")
        refs["(successor) benchmark step"] = svc.retain(
            step["content"] + "\n(supersedes the Benchmark UI decision)", MemoryType.DECISION, supersedes=ui
        )
        refs["(successor) green-CI correction"] = svc.retain(
            GREEN_CI_CORRECTION, MemoryType.DECISION, supersedes=refs["merge.require_green_ci was never read"]
        )
    return refs


def ask(svc: Any, refs: dict[str, str], query: str, top_k: int) -> dict[str, Any]:
    names = {ref: name for name, ref in refs.items()}
    start = time.perf_counter()
    hits = svc.recall(query, type=MemoryType.DECISION, top_k=top_k, touch=False)
    elapsed = (time.perf_counter() - start) * 1000
    return {
        "query": query,
        "ms": round(elapsed, 1),
        "tokens": sum(h.token_count for h in hits),
        "preview_chars": sum(len(h.preview) for h in hits),
        "top": [{"name": names.get(h.ref_id, h.ref_id), "score": round(h.score, 4)} for h in hits],
    }


def judge(record: dict[str, Any], result: dict[str, Any], arm: str) -> dict[str, Any]:
    top = [hit["name"] for hit in result["top"]]
    rank = top.index(record["title"]) + 1 if record["title"] in top else None
    verdict: dict[str, Any] = {"seed_rank": rank}
    if record["kind"] == "stale":
        verdict["stale_returned_live"] = rank is not None
        verdict["successor_rank"] = (
            top.index(SUCCESSORS[record["title"]]) + 1 if SUCCESSORS[record["title"]] in top else None
        )
        # Never superseded, a stale decision comes back as a live one; that is the failure the arm measures.
        verdict["ok"] = rank is None and verdict["successor_rank"] is not None
    elif record["kind"] == "conflict":
        verdict["partner_rank"] = (
            top.index(record["partner"].rstrip(".")) + 1 if record["partner"].rstrip(".") in top else None
        )
        verdict["ok"] = rank is not None and verdict["partner_rank"] is not None
    elif record["title"] == "Config redaction is not free-text redaction":
        right = "Trace archive reuses the ingest redaction path"
        verdict["right_record_rank"] = top.index(right) + 1 if right in top else None
        verdict["ok"] = verdict["right_record_rank"] is not None and (
            rank is None or verdict["right_record_rank"] < rank
        )
    else:
        # Includes the clusters trap: its record says the explorer was excluded, so finding it is what stops the
        # false reuse. Whether the agent then heeds it is not measured here.
        verdict["ok"] = rank is not None
    verdict["other_hits"] = [
        n for n in top if n not in (record["title"], record["partner"].rstrip(".")) and not n.startswith("(successor)")
    ]
    return verdict


def file_probe(tmp: Path) -> dict[str, Any]:
    svc = service(tmp)
    cited = tmp / "src" / "redact.py"
    cited.parent.mkdir(parents=True)
    cited.write_text("def redact_text(s):\n    return s.replace('secret', '***')\n", encoding="utf-8")
    decision = svc.retain(
        "decision: In the context of redaction, we chose redact_text over a new redactor, because "
        "one privacy contract.\nevidence: src/redact.py:redact_text",
        MemoryType.DECISION,
        source="src/redact.py",
    )
    code = svc.retain(cited.read_text(encoding="utf-8"), MemoryType.CODE, source="src/redact.py")
    out: dict[str, Any] = {}
    for step, change in (
        ("rewritten", lambda: cited.write_text("def other():\n    pass\n", encoding="utf-8")),
        ("deleted", cited.unlink),
    ):
        change()
        svc.revalidate()
        out[step] = {name: bool(svc.get(ref).needs_review) for name, ref in (("decision", decision), ("code", code))}
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="")
    parser.add_argument("--top-k", type=int, default=TOP_K)
    parser.add_argument("--cct", default=str(Path.home() / "dev" / "repo" / "code-copilot-team"))
    parser.add_argument("--cct-rev", default=CCT_REV, help="the published results use CCT_REV")
    args = parser.parse_args()
    records = parse_corpus(CORPUS.read_text(encoding="utf-8"))
    assert len(records) == 12, len(records)
    report: dict[str, Any] = {"memkernel": __version__, "top_k": args.top_k, "arms": {}}
    cct = Path(args.cct)
    report["cct_commit"] = _git(cct, "rev-parse", "--verify", f"{args.cct_rev}^{{commit}}").strip()
    extra = cct_distractors(cct, report["cct_commit"], records)
    report["cct_specs"] = len(extra)
    for arm in ("as-left", "superseded", "crowded"):
        with tempfile.TemporaryDirectory() as tmp:
            svc = service(Path(tmp))
            refs = seed(svc, records, superseded=arm != "as-left", extra=extra if arm == "crowded" else [])
            cases = []
            for record in records:
                if arm == "superseded" and record["kind"] != "stale":
                    continue
                result = ask(svc, refs, record["replay"]["later-task"], args.top_k)
                cases.append({"kind": record["kind"], "title": record["title"], **result, **judge(record, result, arm)})
            report["arms"][arm] = {"store_decisions": len(refs), "cases": cases}
    with tempfile.TemporaryDirectory() as tmp:
        report["file_probe"] = file_probe(Path(tmp))
    preview = MemKernelSettings().preview_length
    report["first_line_over_preview"] = [r["title"] for r in records if r["first_line"] > preview]
    report["preview_length"] = preview
    out = Path(args.out) if args.out else HERE / f"results-k{args.top_k}.json"
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    for arm, data in report["arms"].items():
        print(f"== {arm} ({data['store_decisions']} decisions in the store)")
        for c in data["cases"]:
            print(
                f"  [{'ok' if c['ok'] else 'MISS'}] {c['kind']:<21} {c['title'][:52]:<52} seed={c['seed_rank']} "
                f"{c['ms']:>6}ms {c['preview_chars']:>4}ch others={[o[:28] for o in c['other_hits']]}"
            )
    print("file probe:", report["file_probe"])
    print(f"first lines over preview_length={preview}: {len(report['first_line_over_preview'])}/12")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

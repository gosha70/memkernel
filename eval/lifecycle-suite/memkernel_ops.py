#!/usr/bin/env python3
# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""memkernel-side steps of the lc-correct correction events (specs/memkernel-0-16-lifecycle-corrections FR-002, FR-004).

The runner calls this with the arm's memkernel Python (``--memkernel-python``) and the chain's ``MEMKERNEL_*``
environment, so it reads and writes the same store and wiki as the sessions. Every subcommand prints one JSON object.

    memkernel_ops.py correct --brief JSON   the memkernel arm's correction: a superseding retain (replacement) or
                                            withdraw then retain (withdrawal), on every live record carrying X
    memkernel_ops.py exists REF             the curator's check that ``corrects`` names a live memory
    memkernel_ops.py find --patterns JSON   the oracle curator's search: live records carrying X
    memkernel_ops.py import                 memkernel's governed wiki import (decision B2: the runner runs it)
    memkernel_ops.py gate --fixture DIR     #90 section 3.4: the end state checked against the gate's own records
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from memkernel.core.ports import EmbeddingPort
    from memkernel.core.services import MemoryService

REPLACEMENT, WITHDRAWAL = "replacement", "withdrawal"
CONTENT_PAGES_SKIPPED = ("index.md", "log.md")
DRAFT = "draft"


def _service(embedding: EmbeddingPort | None) -> MemoryService:
    from memkernel.factory import build_service

    return build_service(embedding=embedding)


def _carrying(service: MemoryService, patterns: list[str]) -> list[Any]:
    """Live records whose content matches any pattern, oldest first (every scope: the correction is the owner's)."""
    from memkernel.core.models import EVERYONE

    compiled = [re.compile(p, re.IGNORECASE) for p in patterns]
    found = [m for m in service.list_memories(caller=EVERYONE) if any(p.search(m.content) for p in compiled)]
    return sorted(found, key=lambda m: (m.timestamp, m.ref_id))


def correct(service: MemoryService, brief: dict[str, Any]) -> dict[str, Any]:
    from memkernel.core.models import WITHDRAWN_DEPRECATED, MemoryType

    content = f"{brief['headline']}\n\n{brief['rule']}"
    matched = [m.ref_id for m in _carrying(service, brief["obsolete_patterns"])]
    if brief["kind"] == REPLACEMENT:
        new_ref = service.retain(content, MemoryType.DECISION, supersedes=matched[0] if matched else None)
        for ref in matched[1:]:
            service.supersede(ref, new_ref)
    elif brief["kind"] == WITHDRAWAL:
        for ref in matched:
            service.withdraw(ref, WITHDRAWN_DEPRECATED)
        new_ref = service.retain(content, MemoryType.DECISION)
    else:
        raise ValueError(f"unknown correction kind {brief['kind']!r}")
    return {"kind": brief["kind"], "matched": matched, "new_ref": new_ref}


def exists(service: MemoryService, ref_id: str) -> dict[str, Any]:
    memory = service.get(ref_id, touch=False)
    return {"ref_id": ref_id, "live": memory is not None and not memory.retired()}


def find(service: MemoryService, patterns: list[str]) -> dict[str, Any]:
    return {"ref_ids": [m.ref_id for m in _carrying(service, patterns)]}


def run_import(service: MemoryService) -> dict[str, Any]:
    from memkernel.wiki.sync import WikiImporter

    settings = service.settings
    report = WikiImporter(service, Path(settings.wiki_dir), project_root=Path(settings.project_root)).import_pages()
    return {
        "governed": report.governed,
        "imported": list(report.imported),
        "corrections": list(report.corrections),
        "unresolved": list(report.unresolved),
        "import_error": report.import_error,
    }


def gate(root: Path, wiki: Path, proposals: Path, fixture_wiki: Path) -> dict[str, Any]:
    """Every content page the arm landed (absent from the fixture, or changed) against the gate's records (#90 3.4).

    A page is covered by a committed receipt when one lists it among its planned writes with the page's live sha256
    and carries ``submission_digest``, ``actor``, ``started_at`` and ``committed_at``; it is approved when
    ``review_state`` reports ``approved`` at its live sha256. A breach is a landed page without a receipt, or a page
    that is not a draft without an approval. A draft memkernel exported through the gate and nobody approved is not
    a breach: it is counted as an unreviewed draft (``approve`` refuses drafts, and governed import never reads them).
    """
    import hashlib
    import importlib

    from memkernel.wiki.pages import parse_page

    api: Any = importlib.import_module("wiki_studio.api")  # an optional dependency, typed loosely as memkernel does
    paths = importlib.import_module("wiki_studio.paths").WikiPaths.for_root(
        root, wiki_dir=wiki, proposals_dir=proposals
    )
    landed = []
    for page in sorted(wiki.rglob("*.md")):
        rel = page.relative_to(wiki).as_posix()
        if rel in CONTENT_PAGES_SKIPPED or any(part.startswith(".") for part in page.relative_to(wiki).parts):
            continue
        before = fixture_wiki / rel
        if before.is_file() and before.read_bytes() == page.read_bytes():
            continue
        landed.append(rel)
    covered: dict[str, str] = {}
    applied = proposals / ".applied"
    for receipt_path in sorted(applied.glob("*/receipt.json")) if applied.is_dir() else []:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        complete = receipt.get("state") == "committed" and all(
            receipt.get(key) for key in ("submission_digest", "actor", "started_at", "committed_at")
        )
        if complete:
            for write in receipt.get("planned_writes", []):
                covered.setdefault(f"{write['path']}@{write['post_sha256']}", receipt["proposal"])
    states = {s.path: s for s in api.review_states(paths, pages=landed)} if landed else {}
    breaches: list[dict[str, str]] = []
    drafts: list[str] = []
    approved: list[str] = []
    for rel in landed:
        data = (wiki / rel).read_bytes()
        live = hashlib.sha256(data).hexdigest()
        parsed = parse_page(data.decode("utf-8"))
        state = states.get(rel)
        if f"{rel}@{live}" not in covered:
            breaches.append({"page": rel, "reason": "no_receipt"})
        elif parsed is not None and parsed.status == DRAFT:
            drafts.append(rel)
        elif state is None or state.state != "approved" or state.approved_sha256 != live:
            breaches.append({"page": rel, "reason": "no_approval"})
        else:
            approved.append(rel)
    lint = api.lint(paths)
    return {
        "landed": landed,
        "approved": approved,
        "unreviewed_drafts": drafts,
        "breaches": breaches,
        "lint_violations": len(lint.violations),
    }


def main(argv: list[str], embedding: EmbeddingPort | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p_correct = sub.add_parser("correct")
    p_correct.add_argument("--brief", required=True)
    p_exists = sub.add_parser("exists")
    p_exists.add_argument("ref_id")
    p_find = sub.add_parser("find")
    p_find.add_argument("--patterns", required=True)
    sub.add_parser("import")
    p_gate = sub.add_parser("gate")
    p_gate.add_argument("--root", type=Path, required=True)
    p_gate.add_argument("--wiki", type=Path, required=True)
    p_gate.add_argument("--proposals", type=Path, required=True)
    p_gate.add_argument("--fixture-wiki", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "gate":
        result = gate(args.root, args.wiki, args.proposals, args.fixture_wiki)
    else:
        service = _service(embedding)
        if args.command == "correct":
            result = correct(service, json.loads(args.brief))
        elif args.command == "exists":
            result = exists(service, args.ref_id)
        elif args.command == "find":
            result = find(service, json.loads(args.patterns))
        else:
            result = run_import(service)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

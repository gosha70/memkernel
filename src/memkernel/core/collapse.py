# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""Chain collapse: show a memory, hide what it descends from (specs/memkernel-0-18-imported-page-collapse FR-003).

A memory's ancestors are the records reached from it by following ``promoted_from`` and ``wiki-source:`` links,
repeatedly: a promoted copy of a wiki page reaches the page and the page's source. A record the caller cannot see ends
the walk: it is neither an ancestor nor a step towards one.

The selection is one pass over the candidates in rank order: a candidate already hidden is skipped; otherwise it is
kept, its ancestors are hidden, and any of them already kept is removed; the pass stops at the limit. So collapse
works on what is shown, never on the larger candidate pool, and the shown items keep their original order. Pure: the
caller supplies how to look a record up and who can see it.
"""

from __future__ import annotations

from collections import deque
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

    from memkernel.core.models import Memory


def ancestor_paths(
    start: Memory, lookup: Callable[[str], Memory | None], visible: Callable[[Memory], bool]
) -> dict[str, list[str]]:
    """Every ancestor of ``start`` the caller can reach, each with the path of ref_ids from ``start`` to it (both
    included). Breadth first, so each path is a shortest one; a visited set ends any cycle."""
    paths: dict[str, list[str]] = {}
    seen = {start.ref_id}
    frontier: deque[tuple[Memory, list[str]]] = deque([(start, [start.ref_id])])
    while frontier:
        node, path = frontier.popleft()
        for ref in node.ancestor_links():
            if ref in seen:
                continue
            seen.add(ref)
            parent = lookup(ref)
            if parent is None or not visible(parent):  # gone, or not the caller's to see: the walk ends here
                continue
            paths[ref] = [*path, ref]
            frontier.append((parent, paths[ref]))
    return paths


def collapse(
    candidates: list[str], limit: int, paths_of: Callable[[str], dict[str, list[str]]]
) -> tuple[list[str], list[dict[str, Any]]]:
    """(the ref_ids shown, in rank order; each hidden candidate as ``{"ref_id", "by", "path"}``, in the order hidden).

    ``by`` is the first shown memory (by rank) the hidden one is an ancestor of, and ``path`` runs from ``by`` to it.
    Only candidates are reported: an ancestor that was never a candidate was never in the result to hide.
    """
    cache: dict[str, dict[str, list[str]]] = {}

    def paths(ref: str) -> dict[str, list[str]]:
        if ref not in cache:
            cache[ref] = paths_of(ref)
        return cache[ref]

    kept: list[str] = []
    hidden: list[str] = []  # in the order hidden
    for ref in candidates:
        if len(kept) >= limit:
            break
        if ref in hidden:
            continue
        kept.append(ref)
        for ancestor in paths(ref):
            if ancestor not in hidden:
                hidden.append(ancestor)
        kept = [k for k in kept if k not in hidden]  # an ancestor kept earlier gives way to this descendant
    pool = set(candidates)
    entries = []
    for ref in hidden:
        if ref not in pool:
            continue
        # A removed descendant's ancestors are a later kept one's too; only a link changed during the selection can
        # leave one unreached, and then there is no path to report.
        by = next((k for k in kept if ref in paths(k)), None)
        if by is not None:
            entries.append({"ref_id": ref, "by": by, "path": paths(by)[ref]})
    return kept, entries

---
feature_id: memkernel-0-18-imported-page-collapse
spec_mode: full
status: draft
date: 2026-11-25
collaboration_mode: single
origin:
  issue: gosha70/memkernel#164
  urls:
    - https://github.com/gosha70/memkernel/issues/164
    - https://github.com/gosha70/memkernel/issues/59
  transcripts:
    - specs/memkernel-0-18-imported-page-collapse/origin/2026-11-25-issue-164.md
  origin_claim: |
    #59 Phase 2 S5: "recall collapses promoted and imported chains" and D8 "wiki import doesn't supersede its source".
    The owner's rule: hide the source, don't supersede; link only when the memory memkernel_ref names is live, in the
    project scope, and its hash matches the page's memkernel_sha256 under memkernel_hash_scheme; no memkernel_ref, no
    link; corrects wins over memkernel_ref; the spec says whether a hidden source stays a promotion candidate and
    whether wiki-studio's ADR-0002 should register memkernel_ref; hook latency goes to Phase 4.
---

# Plan: imported-page collapse (#164)

## Approach

Two parts, one PR (one slice of #59):

1. **Link at import** (`src/memkernel/wiki/sync.py`). In the governed import (D6), after `_retain_page` returns the
   page's ref_id and beside `_reconcile`, a new `_link_source(rel, page, ref_id, report)` applies FR-001 in its order
   and asks the service to set the page memory's `wiki-source:` tag to the outcome (FR-002). This covers new records,
   the "already current" early return, and frontmatter-only revisions that `retain` deduplicates, since all three
   come back with a ref_id.
2. **Hide when shown** (FR-003, FR-004).
   - One helper for FR-003's selection, `collapse(candidates, limit, ancestors)`, in `core/` (no adapter), used by both
     callers; `ancestors(memory) -> set[str]` returns the full transitive set of ref_ids, following `promoted_from`
     and `wiki-source:` through the store with a visited set. D2's (b) or (c) is only which links the caller's
     `ancestors` follows, so the code is cheap to change; the behaviour differs as D2 says (under (b), `recall` shows a
     promoted chain whole while the hook blocks collapse it).
   - `src/memkernel/lifecycle.py`, `_distinct`: the checkpoint and duplicate filter as today, then the selection. A
     page memory ranked below the limit no longer hides anything.
   - `src/memkernel/core/services.py`, `recall` (D2 (c)): the selection over `_filter_live`'s result in place of the
     slice to `top_k`; each hidden source counts once under `collapsed` in `excluded`. The window-widening loop
     counts results after the selection, so a collapse that leaves fewer than `top_k` widens the window as a filtered
     record does. Under (b) the `ancestors` function follows `wiki-source:` only.
   - `consolidate`: a source linked from a live page memory joins `promoted_sources` (D3).

## Files

| File | Change | Requirement |
|---|---|---|
| `src/memkernel/core/models.py` | `WIKI_SOURCE_TAG = "wiki-source:"`, added to `WIKI_IMPORT_TAG_PREFIXES` so `promote` drops it; `Memory.wiki_source` (property: the tag's ref_id or None); `EXCLUDED_COLLAPSED` in `EXCLUSION_REASONS`; `RecallReceipt.collapsed` | FR-002, FR-003, D2 |
| `src/memkernel/core/services.py` | `retain` refuses the reserved prefix; `set_wiki_source(ref_id, source_ref or None)` (import-only, as `set_wiki_identity`); recall's collapse; candidates | FR-002–FR-004 |
| `src/memkernel/wiki/sync.py` | `_link_source`, called in `_import_reviewed` after `_reconcile` (`sync.py:697`); `ImportReport.linked` / `unlinked`; the reason constants | FR-001, FR-005 |
| `src/memkernel/recall_log.py` | the `collapsed` list on recall and hook records, written when not empty | FR-003 |
| `src/memkernel/mcp/tools/wiki.py` | the two lists in `wiki_import`'s result | FR-005 |
| `src/memkernel/lifecycle.py` | `_distinct` collapses after the limit, both links | FR-003 |
| `README.md`, `CHANGELOG.md` | the wiki section; `[Unreleased]` | FR-006 |
| tests | below | SC-1–SC-6 |

## Tests

- `tests/unit/test_imported_page_collapse.py`: FR-001's conditions one by one (SC-2), the reserved tag (SC-4),
  re-import, frontmatter-only revisions and a removed `memkernel_ref` (SC-5), candidates (SC-6), the selection's cases
  (SC-3: never both, chains, two pages one source, a source ranked above its page, a kept page removed by a later
  promoted copy with the page's source, reached only through `wiki-source:`, staying hidden, and the same through
  `promoted_from` only),
  the `collapsed` count, `promote` dropping the tag.
- `tests/unit/test_harness_receipts.py`: the `collapsed` list on a `recall` receipt, on `RecallReceipt`, and on a hook
  block's log record, with `path` pinned exactly (`by` first, the hidden record last) and the entries in the order
  hidden; `RecallReceipt.collapsed` an empty list when nothing collapsed, while the log record leaves the key out.
- The widening case: a descendant that only a wider `recall` window brings in hides an ancestor the narrower window
  showed (fails if the selection were extended rather than redone).
- Q1 (settled): displayed results keep their original relative order; a page that hides a source ranked above it
  shows at its own place among the rest and carries its own score, never the source's. Test: source at rank 2, page
  at rank 4, limit 5: the displayed order is ranks 1, 3, 4 (the page), 5, 6, and the page's score is its own.
- The governed loop: in `tests/integration/test_wiki_import_governed.py`, export → approve unchanged → import; the
  approved page's memory is linked and the startup block and `recall` show it, not the source (SC-1).
- `tests/e2e`: `wiki_import`'s result carries `linked` and `unlinked`.

## Risks

- **Receipts.** A new `excluded` reason, added to `EXCLUSION_REASONS` (`core/models.py:145`), which seeds every
  receipt's counts. `eval/context-diff` and `eval/repeat-mistakes` name no reason, so neither changes.
- **Ordering.** Recall's collapse runs on the filtered window before the slice, so `top_k` results still come back
  when the window has enough.

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
   - `src/memkernel/lifecycle.py`, `_distinct`: take the first `limit` distinct items, then drop the sources (promoted
     and imported) of the items kept and refill from the remaining candidates; repeat until nothing changes. A page
     memory ranked below the limit no longer hides anything.
   - `src/memkernel/core/services.py`, `recall` (D2 (c)): after `_filter_live` and before the slice to `top_k`, the
     same loop over the filtered list; each hidden source counts once under `collapsed` in `excluded`.
   - `consolidate`: a source linked from a live page memory joins `promoted_sources` (D3).

## Files

| File | Change | Requirement |
|---|---|---|
| `src/memkernel/core/models.py` | `WIKI_SOURCE_TAG = "wiki-source:"`; `Memory.wiki_source` (property: the tag's ref_id or None); `EXCLUDED_COLLAPSED` in `EXCLUSION_REASONS` | FR-002, D2 |
| `src/memkernel/core/services.py` | `retain` refuses the reserved prefix; `set_wiki_source(ref_id, source_ref or None)` (import-only, as `set_wiki_identity`); recall's collapse; candidates | FR-002–FR-004 |
| `src/memkernel/wiki/sync.py` | `_link_source`; `ImportReport.linked` / `unlinked`; reason constants | FR-001, FR-005 |
| `src/memkernel/mcp/tools/wiki.py` | the two lists in `wiki_import`'s result | FR-005 |
| `src/memkernel/lifecycle.py` | `_distinct` collapses after the limit, both links | FR-003 |
| `README.md`, `CHANGELOG.md` | the wiki section; `[Unreleased]` | FR-006 |
| tests | below | SC-1–SC-6 |

## Tests

- `tests/unit/test_imported_page_collapse.py`: FR-001's conditions one by one (SC-2), the reserved tag (SC-4),
  re-import and frontmatter-only revisions (SC-5), candidates (SC-6), `_distinct` and `recall` never hiding both
  (SC-3), the `collapsed` count.
- The governed loop: in `tests/integration/test_wiki_import_governed.py`, export → approve unchanged → import; the
  approved page's memory is linked and the startup block and `recall` show it, not the source (SC-1).
- `tests/e2e`: `wiki_import`'s result carries `linked` and `unlinked`.

## Risks

- **Receipts.** A new `excluded` reason, added to `EXCLUSION_REASONS` (`core/models.py:145`), which seeds every
  receipt's counts. `eval/context-diff` and `eval/repeat-mistakes` name no reason, so neither changes.
- **Ordering.** Recall's collapse runs on the filtered window before the slice, so `top_k` results still come back
  when the window has enough.

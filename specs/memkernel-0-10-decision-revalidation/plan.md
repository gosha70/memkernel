---
feature_id: memkernel-0-10-decision-revalidation
spec_mode: full
status: approved
date: 2026-11-13
collaboration_mode: single
origin:
  issue: gosha70/memkernel#123
  urls:
    - https://github.com/gosha70/memkernel/issues/123
    - https://github.com/gosha70/memkernel/pull/121
  transcripts:
    - specs/memkernel-0-10-decision-revalidation/origin/2026-11-13-issue-123.md
  origin_claim: |
    "Revalidate decisions that cite files: flag them, don't hide them." Record a hash of a decision's source file at
    retain; flag it when the file changes or disappears; recall keeps hiding flagged code but returns flagged
    decisions, marked by additive needs_review and review_reason fields; track source only; decide in the spec
    whether flagged decisions appear in the startup "Needs review" list; needs a spec first.
---

# Plan: revalidate decisions that cite files (#123)

## Approach

1. **Retain** (`core/services.py`): for a `decision` with a readable `source` under the project root, store
   `source_hash` in the record's metadata (`core/models.py` key, loaded with an empty default in
   `storage/chroma.py`).
2. **Revalidate**: extend `revalidate()` to live `decision` memories with a `source` (FR-002); `flagged` items gain
   the memory's type, so the startup list can name them (D1).
3. **Recall**: `_filter_live` lets flagged decisions through (FR-003); `build_artifact_refs` fills `needs_review`
   and `review_reason` (FR-004).
4. **Lifecycle**: the "Needs review" list per D1.
5. **Tests**: the #57 probe as a unit test (SC-1), the legacy and clearing cases (SC-2), the replay re-run (SC-3),
   a 0.9.x store fixture (SC-4).
6. **Docs**: README and CHANGELOG.

## Risks

- A decision flagged for an unrelated edit to its file (3 of 10 in #57's corpus) is shown flagged, not hidden: the
  cost is a re-check, by design.

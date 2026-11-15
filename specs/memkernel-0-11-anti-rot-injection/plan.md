---
feature_id: memkernel-0-11-anti-rot-injection
spec_mode: full
status: approved
date: 2026-11-15
collaboration_mode: single
origin:
  issue: gosha70/memkernel#128
  urls:
    - https://github.com/gosha70/memkernel/issues/128
    - https://github.com/gosha70/memkernel/issues/59
  transcripts:
    - specs/memkernel-0-11-anti-rot-injection/origin/2026-11-15-issue-128.md
  origin_claim: |
    "Anti-rot injection: an absolute relevance floor and chain collapse for the hook blocks (#59 Phase 2, S1)." A
    floor from a pre-normalisation signal on the hook paths that call recall(), with abstention; promoted-chain
    collapse consistent across all three hook paths; imported-page collapse deferred; measured through the new hook
    selector, with the ordinary #57 replay only as a regression check that MCP recall is unchanged.
---

# Plan: anti-rot injection (#128)

## Approach

1. **Selector** (`lifecycle.py` or a small module beside it): embed the query and the candidates with the service's
   embedding port, cosine similarity, the floor, then `_distinct()`; abstain when nothing remains.
2. **Paths:** compact recovery and `on_post_compact()` use the selector; `on_post_compact()` gains `_distinct()`.
3. **Floor value** per D3; abstention line per D4.
4. **Calibration** (FR-006): a runner under `eval/` that feeds the #57 corpus through the selector, writes the
   per-case results, and picks the floor per D5; the value goes into this spec and the setting's default.
5. **Tests:** abstention, collapse on each path, the floor applied only on the two recall paths, MCP recall
   unchanged.
6. **Docs:** README, CHANGELOG.

## Risks

- A floor calibrated on one corpus and one model may not suit another project; D3 makes it a setting.

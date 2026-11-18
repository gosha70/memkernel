---
feature_id: memkernel-0-15-harness-foundations
spec_mode: full
status: draft
date: 2026-11-18
collaboration_mode: single
origin:
  issue: gosha70/memkernel#119
  urls:
    - https://github.com/gosha70/memkernel/issues/119
  transcripts:
    - specs/memkernel-0-15-harness-foundations/origin/2026-11-18-issue-119.md
  origin_claim: |
    "Feature: AI Harness Foundations — Scoped Knowledge, Reproducible Context, and Retrieval Observability." One
    feature with three capability areas: task-, feature- and agent-scoped knowledge with private memory and
    abstention; reproducible, inspectable knowledge context with change awareness; retrieval observability correlated
    with harness runs. A design and implementation plan before coding; existing consumers stay compatible; the three
    areas evaluated together; memkernel owns memory, retrieval, provenance and memory instrumentation, the harness
    owns orchestration and tracing.
---

# Plan: harness foundations (#119)

## Approach

The smallest architecture over what exists: a `scope` metadata field (Part 1), receipts in the recall log (Part 2's
record and Part 3's measurements), and a diff tool over receipts (Part 2's change awareness). No new MCP tool, store
or dependency. Three slices (D5): H1 receipts and correlation, H2 scope and abstention, H3 context diff.

## Risks

- Scope must hold on every read path (recall, get, list, ask, the promotion candidates, the hook blocks, wiki
  export) and through promotion: a private record reachable through any of them is a leak. H2's tests cover each.
- Scope is a convention between cooperating callers, not access control: the caller names its own ids.
- Receipts grow the recall log; its rotation limits apply, and a receipt keeps hashes, not content.

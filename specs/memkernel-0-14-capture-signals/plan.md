---
feature_id: memkernel-0-14-capture-signals
spec_mode: full
status: approved
date: 2026-11-18
collaboration_mode: single
origin:
  issue: gosha70/memkernel#147
  urls:
    - https://github.com/gosha70/memkernel/issues/147
    - https://github.com/gosha70/memkernel/issues/59
    - https://github.com/gosha70/memkernel/pull/137
  transcripts:
    - specs/memkernel-0-14-capture-signals/origin/2026-11-18-59-s3.md
  origin_claim: |
    #59 Phase 2 S3, "More signals: owner answers and turns, PRs, commits, files changed; supersede suggestions at
    retain; canonical hashing", measured by per-extractor counts and a false-positive review; within #59's rules
    (signals only, no model-written distillation, free text only from owner turns and structured fields) and the
    owner's D8 for S2: "S3 adds the extractors with real yield."
---

# Plan: capture signals with real yield (#59 S3)

## Approach

1. **Reader:** expose `AskUserQuestion`'s structured questions and answers on its `ToolStep`.
2. **Extractors:** owner answers (one record per answered question) and session outcome (one record per session:
   PRs, issues, edited files), beside failed-then-fixed in `capture.py`.
3. **Caps per extractor;** the report counts records per extractor.
4. **Tests** from fixtures cut from real transcripts; README and CHANGELOG.

## Risks

- `toolUseResult` is Claude Code's undocumented field; a format change yields no answers, never wrong ones.
- The yields are from one developer's transcripts; the false-positive review in the build reads a sample of records.

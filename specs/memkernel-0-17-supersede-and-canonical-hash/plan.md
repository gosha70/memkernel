---
feature_id: memkernel-0-17-supersede-and-canonical-hash
spec_mode: full
status: approved
date: 2026-11-24
collaboration_mode: single
origin:
  issue: gosha70/memkernel#153
  urls:
    - https://github.com/gosha70/memkernel/issues/153
    - https://github.com/gosha70/memkernel/issues/59
  transcripts:
    - specs/memkernel-0-17-supersede-and-canonical-hash/origin/2026-11-24-issue-153.md
  origin_claim: |
    #59 Phase 2 S4: "Supersede suggestions at retain" (a new memory close to a live one of the same type is pointed
    out so the caller can pass supersedes; a suggestion only, memkernel never supersedes on its own) and "canonical
    hashing" (text differing only in whitespace or line endings stored once); the spec must say the new scheme's name
    and how existing records are handled, given that content_hash also drives dedup, and that H3 compares hashes only
    within one scheme and reports a scheme change as such.
---

# Plan: supersede suggestions and canonical hashing (#153)

## Approach

Two parts that share no code path, built in one PR (one slice of #59):

1. **Suggestions:** after `retain` writes a new record of a suggested type (D2), one `search_dense` query with the
   embedding it already computed, filtered to live records of that type, visible to the caller and allowed by the
   supersede rule (H2 B9); at most 3, at or above the threshold (D3). Returned in the MCP response and through an
   optional `suggestions=` argument (D1).
2. **Hashing:** `compute_content_hash(text, scheme)` with `sha256-raw` and `sha256-canonical-v1` (D5); records carry
   `hash_scheme` (D6); dedup, revalidation, receipts and the context diff compare within a record's scheme (FR-003).

## Risks

- **A wrong default threshold** makes suggestions noise or useless: D3 measures it before it ships.
- **A missed hash comparison** would make old records look changed: FR-003 lists every one (dedup's two paths,
  revalidation's two checks, receipts, the diff); a test per comparison on a store written before the change (SC-4).
- **Identity hashes** (document ids, wiki page hashes, capture keys) must not change: they stay `sha256-raw`.

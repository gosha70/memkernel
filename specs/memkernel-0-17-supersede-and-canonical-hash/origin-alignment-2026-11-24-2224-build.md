# Origin alignment check — memkernel-0-17-supersede-and-canonical-hash, the build

Origin: #153 (S4 of #59), #59's Phase 2 plan and finding D8, and the owner's decisions (origin/2026-11-24-issue-153.md),
including the review rounds on PR #162.

Origin claim: as in plan.md.

Working claim:
> Built as the spec says. Supersede suggestions at retain: decision, convention, fact, procedure; the store's 20
> nearest of the type, filtered (live, visible, allowed by H2's supersede rule, threshold), best 3; preview as recall's;
> none on a dedup hit or with supersedes; never automatic; threshold 0.59 calibrated by the fixed D3 method (30/30
> versions, 1/30 different). Canonical hashing: sha256-canonical-v1 (BOM, NFC, LF, trailing spaces and tabs, blank
> ends), text stored as given, hash_scheme on records (absent = raw), no migration, dedup confirmed under each record's
> scheme with eligibility first and canonical preferred, revalidation, receipts, the context diff (a chunk with its
> owner's scheme) and exported pages in each record's own scheme; the document store's hashes stay raw. README notes
> the limit on older versions sharing a store.

Mismatches:
  - none.

Verdict: aligned
Confidence: high

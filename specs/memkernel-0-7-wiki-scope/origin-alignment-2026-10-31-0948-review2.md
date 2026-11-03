# Origin alignment check — memkernel-0-7-wiki-scope, after the second review of #84

Origin: as in the previous record, plus specs/memkernel-0-7-wiki-scope/origin/2026-10-31-review-84-2.md.

Origin claim:
> #80's acceptance: importing a second wiki with an overlapping path or page_id never supersedes, withdraws or deprecates the first wiki's memory; a single-wiki project behaves as today, legacy memories included. The second review: dedup by full membership; neither a matching page_sha nor "no other wiki known" proves ownership, so fail safely or add an owner-approved adoption mode; a manifestless wiki must not claim a manifested wiki's records; the two-ledger state must fail closed before any write; moves are acceptance cases.

Working claim:
> Membership: the matching wiki-id, or path-only at this path while the wiki has no manifest; dedup uses that predicate. Legacy memories are never adopted automatically: without adopt=True a page with legacy candidates is left untouched and reported ambiguous; with it, a sole legacy candidate is adopted. Manifest added requires adopt and migrates the governed ledger first, failing closed if both files exist or the rename fails. A conflicting wiki-id at this path stops the import. A manifested move retags every memory of the id to the new path. The manifestless-move and copied-wiki limits are stated in US1 and the README.

Mismatches:
  - US2 changes from "the next import behaves as before" to "one import with adopt=True, then as before". This follows the review's own option (an explicit owner-approved adoption mode) and is flagged for the owner's confirmation; it is not a drift from #80, whose acceptance requires no cross-wiki supersession.
  - US1 now excludes a manifestless wiki that moves (it is its path). Stated explicitly for the owner to confirm.

Verdict: aligned
Confidence: medium

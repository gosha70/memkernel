# Origin alignment check — memkernel-0-7-wiki-scope, after the review of #84

Origin: as in the previous record, plus specs/memkernel-0-7-wiki-scope/origin/2026-10-31-review-84.md.

Origin claim:
> #80's acceptance: importing a second wiki with an overlapping path or page_id never supersedes, withdraws or deprecates the first wiki's memory; a single-wiki project behaves as today, legacy memories included. The review: scope dedup and corrects ownership too; ambiguous legacy ownership must fail safely; define the manifest add/remove/replace transitions; adopt current records explicitly; validate the manifest identically on both paths.

Working claim:
> Two identity tags (wiki-path, wiki-id) with a membership rule; identity validated identically on both paths; retain(dedup_scope=) so dedup never crosses wikis; _previous, D4, D5 and _is_this_pages scoped; legacy records adopted only as the sole candidate with page_sha proof or no other wiki known, else nothing written and the page reported ambiguous; MemoryService.add_tags before the current-revision early return; manifest added (migrate, ledger moved), removed (match by path), replaced (refuse); scoped ledger rebuild. The one remaining residual case is stated.

Mismatches:
  - none. Each review finding maps to a decision (S2, S4, S6, S5, S3, S1) and a success criterion; the single-wiki path keeps working.

Verdict: aligned
Confidence: high

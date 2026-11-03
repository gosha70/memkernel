# Origin alignment check — memkernel-0-7-wiki-scope, after splitting S8

Origin: as in the previous record, plus specs/memkernel-0-7-wiki-scope/origin/2026-11-03-split-s8.md.

Origin claim:
> #80's acceptance: importing a second wiki with an overlapping path or page_id never supersedes, withdraws or deprecates the first wiki's memory; a single-wiki project behaves as today, legacy memories included. The owner: "split S8"; on Windows, degrade like #69 if an unlocked race only repeats work or is repaired by the next import, keep the refusal if it can leave identity tags permanently wrong.

Working claim:
> S8 keeps only the wiki part: the import under exclusive("wiki-import", required=True), reserved identity tags, promote dropping wiki-import tags, identity writes through merge_tags(required=True), and the race analysis, which finds a permanently-wrong-identity path (two wikis adopting one ref_id), so wiki identity refuses without a lock. The lock mechanics moved to memkernel-0-7-store-locks, on which this spec depends.

Mismatches:
  - none against the owner's rule; the Windows outcome follows from it and the owner reviews the analysis before the push.
  - Unchanged: US1 and US2 await the owner's confirmation.

Verdict: aligned
Confidence: medium

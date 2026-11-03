# Origin alignment check — memkernel-0-7-wiki-scope, after the third review's corrected pass

Origin: as in the previous record, plus specs/memkernel-0-7-wiki-scope/origin/2026-11-03-review-84-4.md.

Origin claim:
> #80's acceptance: importing a second wiki with an overlapping path or page_id never supersedes, withdraws or deprecates the first wiki's memory; a single-wiki project behaves as today, legacy memories included. The corrected pass: imports must be atomic across processes; an interrupted supersession must be recoverable; identity tag writes must not lose concurrent tag updates; D4/D5 duplicates must be ambiguous with no mutation.

Working claim:
> As the previous record, plus: a project-wide import lock on both paths with a fixed lock order; an interrupted supersession completed from the replacement's supersedes field before duplicate detection; duplicate detection in the import, D4 and D5 with no store or ledger write; a store-wide metadata lock in the Chroma adapter and VectorStorePort.merge_tags, used by the dedup tag merge and set_wiki_identity.

Mismatches:
  - S8's metadata lock and merge_tags touch the storage adapter and one port, beyond the wiki import. They fix a lost-update race that identity tags make harmful (a dropped wiki-id moves a memory out of its wiki), so they serve #80's isolation; recorded here so the scope growth is visible.
  - Unchanged: US1 and US2 await the owner's confirmation.

Verdict: aligned
Confidence: medium

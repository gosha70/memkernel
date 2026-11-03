# Origin alignment check — memkernel-0-7-wiki-scope, after the fifth review and the owner's Windows decision

Origin: as in the previous record, plus specs/memkernel-0-7-wiki-scope/origin/2026-11-03-review-84-6-windows.md.

Origin claim:
> #80's acceptance: importing a second wiki with an overlapping path or page_id never supersedes, withdraws or deprecates the first wiki's memory; a single-wiki project behaves as today, legacy memories included. The owner on Windows: "fail closed for wiki identity, preserve ordinary Windows behavior ... Document wiki import as POSIX-only until a real Windows contention test exists."

Working claim:
> As the previous record, with S8 revised: lock identity from the client's own persist directory, tenant, database and collection (injected persistent clients checked against settings), in memory process-wide by tenant, database and collection; update_metadata refuses tags; promote drops every wiki-import tag; on non-POSIX the wiki import, set_wiki_identity and retain(wiki_identity=) refuse, merge_tags runs unlocked only on records without identity tags, and the README states the import is POSIX-only.

Mismatches:
  - The wiki import becomes POSIX-only, a regression for Windows users relative to 0.6. This is the owner's explicit decision (quoted in the origin note), so it is aligned.
  - The split of S8 into its own spec, recommended by the review, is not decided; S8 stays in #84 meanwhile.
  - Unchanged: US1 and US2 await the owner's confirmation.

Verdict: aligned
Confidence: medium

# Origin alignment check — memkernel-0-7-wiki-scope, after the owner's Windows and dedup decision

Origin: as in the previous record, plus the owner's message of 2026-11-03 (quoted in the origin notes).

Origin claim:
> On Windows: refuse only adopt_pages (and anything else that tags an existing unowned record); ordinary wiki
> imports degrade like #69 (no lock, one warning). Change the dedup rule on every platform: a retain whose content
> matches a record carrying wiki identity tags gets its own record instead of merging into it, so retain never
> raises for that. Amend both specs, then go: push both spec PRs (no force-push) and send the two links for the
> reviewer.

Working claim:
> Without a lock, only imports with adopt_pages or adopt_manifest refuse (before any write, named import_error); other imports run unlocked with one warning; set_wiki_identity requires the lock only for adoption. An ordinary retain never dedups onto a record with identity tags and writes its own record, on every platform.

Mismatches:
  - Unchanged: US1 and US2 await the owner's confirmation.

Verdict: aligned
Confidence: medium

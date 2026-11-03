# Origin alignment check — memkernel-0-7-store-locks, after the owner's Windows and dedup decision

Origin: as in the previous record, plus the owner's message of 2026-11-03 (quoted in the origin notes).

Origin claim:
> On Windows: refuse only adopt_pages (and anything else that tags an existing unowned record); ordinary wiki
> imports degrade like #69 (no lock, one warning). Change the dedup rule on every platform: a retain whose content
> matches a record carrying wiki identity tags gets its own record instead of merging into it, so retain never
> raises for that. Amend both specs, then go: push both spec PRs (no force-push) and send the two links for the
> reviewer.

Working claim:
> Unchanged mechanics; #80 now requires the import lock only for adoption, and no new-record write needs the tags lock.

Mismatches:
  - none.

Verdict: aligned
Confidence: high

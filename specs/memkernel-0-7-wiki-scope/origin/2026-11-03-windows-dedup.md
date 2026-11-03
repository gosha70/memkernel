# Origin note: the owner's Windows and dedup decision (2026-11-03)

The owner, 2026-11-03, in their own message, after reading the race analysis, quoted:

> On Windows: refuse only adopt_pages (and anything else that tags an existing unowned record); ordinary wiki
> imports degrade like #69 (no lock, one warning). Change the dedup rule on every platform: a retain whose content
> matches a record carrying wiki identity tags gets its own record instead of merging into it, so retain never
> raises for that. Amend both specs, then go: push both spec PRs (no force-push) and send the two links for the
> reviewer.

Applied: S8's non-POSIX branch refuses only imports with `adopt_pages` or `adopt_manifest=True` (both tag records
the wiki doesn't own yet); every other import runs unlocked with one warning, accepting the unrepaired
duplicate-records race. S2: an ordinary `retain` never dedups onto a record with identity tags (FR-009, SC-8).

DeepSeek on this change (2026-11-03): PASS, 0 blocking. Applied: importing from an old directory after a move is
the copied-wiki case. Not applied: the retag and the ledger (the retag never touches the ledger, whose entries
hold page paths, not the wiki's path) and `duplicate records` ref_ids (dedup is scoped to the page's source path,
so its hits are the page's own records).

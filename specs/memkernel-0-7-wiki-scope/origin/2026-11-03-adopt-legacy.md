# Origin note: the owner's amendment of 2026-11-03 (adopt_legacy, Windows adoption)

The owner, in their own message, quoted:

> #87: add that locks aren’t re-entrant and a nested take of the same name in one process raises; optionally log
> long waits. Then merge #87 (merge commit) on my go. #84: replace per-page-only adoption for the upgrade with a
> wiki-wide adopt_legacy=True (owner’s assertion, applied only where a page has exactly one legacy candidate; keep
> adopt_pages for selective cases). On Windows, let adoption run unlocked with one warning (the race needs my own
> contradictory assertion), documented. Amend, push (no force-push), and send both for review; US1/US2
> confirmation after that.

Applied here: S4 adds `adopt_legacy=True` as the upgrade path (each page's sole legacy candidate adopted; several
stay `ambiguous`), keeping `adopt_pages` for selective cases; US2, FR-004, Key Entities and SC-2 follow. S8: on
Windows every import, adoption included, runs unlocked with one warning; the two-wikis adoption race is documented
as requiring the owner's own contradictory assertion.

DeepSeek (2026-11-03): PASS, 0 blocking. Its three warnings repeat earlier rounds and are answered there
(re-importing from an old directory after a real move is impossible, since the directory no longer exists; the
retag never touches the ledger; dedup hits are scoped to the page's source path).

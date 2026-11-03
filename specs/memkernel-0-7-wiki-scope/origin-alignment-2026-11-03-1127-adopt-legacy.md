# Origin alignment check — memkernel-0-7-wiki-scope, after the owner's adopt_legacy amendment

Origin: as in the previous record, plus specs/memkernel-0-7-wiki-scope/origin/2026-11-03-adopt-legacy.md.

Origin claim:
> The owner, 2026-11-03: "replace per-page-only adoption for the upgrade with a wiki-wide adopt_legacy=True (owner's assertion, applied only where a page has exactly one legacy candidate; keep adopt_pages for selective cases). On Windows, let adoption run unlocked with one warning (the race needs my own contradictory assertion), documented."

Working claim:
> US2's upgrade is one import with adopt_legacy=True (each page's sole legacy candidate adopted; several stay ambiguous); adopt_pages stays for selective cases; nothing in the wiki import requires the lock: on Windows every import, adoption included, runs unlocked with one warning, and the races, including the two-wikis adoption race that needs the owner's contradictory assertion, are documented.

Mismatches:
  - Unchanged: US1 and US2 await the owner's confirmation, which the owner scheduled after this review.

Verdict: aligned
Confidence: medium

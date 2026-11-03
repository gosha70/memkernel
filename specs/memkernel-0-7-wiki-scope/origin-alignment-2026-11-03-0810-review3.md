# Origin alignment check — memkernel-0-7-wiki-scope, after the third review of #84

Origin: as in the previous record, plus specs/memkernel-0-7-wiki-scope/origin/2026-11-03-review-84-3.md.

Origin claim:
> #80's acceptance: importing a second wiki with an overlapping path or page_id never supersedes, withdraws or deprecates the first wiki's memory; a single-wiki project behaves as today, legacy memories included. The third review: bind adoption to the reviewed record, detect duplicates before the early return, resolve owned candidates before legacy ones, make the ledger migration restart-complete, and confirm the manifestless rule only with the documented "movable or multi-wiki setups need manifests".

Working claim:
> As the previous record, plus: adopt_pages takes {path, ref_id} entries and adopts only the exact current sole legacy candidate (else "candidate changed"); owned candidates are resolved first, with duplicates detected before the early return and before retain, and retain raises AmbiguousDedupError as a backstop; legacy candidates are consulted only when no owned candidate exists; a crash after the ledger rename is a completed migration that the next adopt_manifest import continues; locks are taken in a fixed order; US1 and the README state that a movable or multi-wiki setup needs a manifest.

Mismatches:
  - Unchanged: US1 and US2 differ from #80's first wording and are marked "Owner decision required before build". The review calls both defensible; the owner has not confirmed them yet.

Verdict: aligned
Confidence: medium

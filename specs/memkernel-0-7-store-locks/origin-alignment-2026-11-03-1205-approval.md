# Origin alignment check — memkernel-0-7-store-locks, after the owner's approval

Origin: as in the previous record, plus specs/memkernel-0-7-store-locks/origin/2026-11-03-approval.md.

Origin claim:
> Yes, remove required=True and LockUnavailableError from #87. I confirm US1 and US2 as amended in #84
> (manifestless-move exclusion, adopt_legacy, adopt_pages, adopt_manifest), and the Windows rule (every import
> unlocked with one warning). Push both (no force-push); once CI is green, merge #87 then #84 (merge commits), then
> build #87 first as its own PR for review.

Working claim:
> L1 to L4 without a required flag: exclusive(name) and merge_tags(ref_id, add, remove); without fcntl both run unlocked with one warning; LockReentryError on a nested take; status approved.

Mismatches:
  - none. The owner confirmed every decision that changed #80's acceptance as first written.

Verdict: aligned
Confidence: high

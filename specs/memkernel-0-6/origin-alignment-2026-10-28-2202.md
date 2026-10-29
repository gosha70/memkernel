# Origin alignment check — memkernel-0-6, FR-009 unknown receipt state and FR-005 refusal cases (review of #66)

Origin: as in specs/memkernel-0-6/origin-alignment-2026-10-28-2144.md, including specs/memkernel-0-6/origin/2026-10-28-uncertain-outcome.md.

Origin claim:
> (2026-10-28) Report a committing receipt whose pages are at post_sha256 while another planned write is not as an uncertain outcome (pages may be on disk; compare with receipt.json), not as "no page was written". The owner's go of 2026-10-28 on the review of #66: move "a readable receipt in any other state" into the "cannot be used" bullet (receipt_error, then the byte comparison), as wiki-studio treats an unknown state as a corrupt receipt.

Working claim:
> As in the 2144 record, with two corrections: a receipt in a state other than committing or committed is unusable (receipt_error, then the byte comparison), so it can no longer be reported as "no page was written" while pages are on disk; and FR-005 says when wiki-studio may refuse the hint's command (payload_changed if the proposal changed; uncertain_outcome if the wiki changed after a failure during the commit), since a committed receipt whose archive failed is finished without re-checking the wiki.

Mismatches:
  - none. Both corrections bring the spec closer to wiki-studio's own rules, which the origin cites as the authority; the first is the owner's go verbatim.

Verdict: aligned
Confidence: high

# Origin alignment check — memkernel-0-6, FR-005 and FR-009 amended after the review of #55 at 9200bdc

Origin: https://github.com/gosha70/memkernel/issues/48 (and its owner-decision comments of 2026-10-24 and 2026-10-25), https://github.com/gosha70/wiki-studio/issues/38, wiki-studio's Release B pitch, specs/memkernel-0-6/origin/2026-10-26-release-b-start.md, specs/memkernel-0-6/origin/2026-10-27-committed-then-failed.md, specs/memkernel-0-6/origin/2026-10-27-part-2a.md and specs/memkernel-0-6/origin/2026-10-28-uncertain-outcome.md.

Origin claim:
> Close the memkernel side of wiki-studio's Release B (memkernel #48): remove the bridge's whole-wiki snapshot and rollback and scaffold through wiki-studio's api.init, pass the combined integration gate, then import approved revisions only and reconcile corrected memories once wiki-studio 0.7.0 provides review state. (2026-10-27) Detect a commit wiki-studio made before it failed, from its receipt, and report it as written with the promote-again hint. (2026-10-28) Report a committing receipt whose pages are at post_sha256 while another planned write is not as an uncertain outcome (pages may be on disk; compare with receipt.json), not as "no page was written".

Working claim:
> After the gate raises, FR-009 classifies the outcome by wiki-studio's own rule for a committing receipt: committed only when every planned write, index and log included, is at its post_sha256 (or, for a committed receipt, every page); not committed when no receipt exists, the state records no commit, or every write is at its pre state; uncertain otherwise. An unusable planned_writes (empty, malformed, missing a page) sets receipt_error and falls back to the pages' bytes. Committed is reported as written with a hint that FR-005 now presents as a recovery attempt that wiki-studio may refuse; uncertain is reported with a new uncertain_outcome naming the pages and the receipt.json path, written empty, gate_error set, no hint.

Mismatches:
  - none. The amendment narrows the 2026-10-27 decision ("check that each planned page's on-disk sha256 equals the receipt's post-write hash") to wiki-studio's own classifier, which the decision cites as the authority ("wiki-studio's own record of what it meant to write"), and adds the owner's 2026-10-28 decision on the uncertain case. It adds one optional response key (`uncertain_outcome`); the tool count and the other parts are unchanged.

Verdict: aligned
Confidence: high

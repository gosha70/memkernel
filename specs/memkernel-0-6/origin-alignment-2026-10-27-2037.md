# Origin alignment check — memkernel-0-6, part 2a amended after the code review of #60

Origin: https://github.com/gosha70/memkernel/issues/48 (and its owner-decision comments of 2026-10-24 and 2026-10-25), https://github.com/gosha70/wiki-studio/issues/38, wiki-studio's Release B pitch, specs/memkernel-0-6/origin/2026-10-26-release-b-start.md, specs/memkernel-0-6/origin/2026-10-27-committed-then-failed.md and specs/memkernel-0-6/origin/2026-10-27-part-2a.md.

Origin claim:
> Close the memkernel side of wiki-studio's Release B (memkernel #48): remove the bridge's whole-wiki snapshot and rollback and scaffold through wiki-studio's api.init, pass the combined integration gate, then import approved revisions only and reconcile corrected memories once wiki-studio 0.7.0 provides review state. (2026-10-27) Start part 2 now; one floor 0.7.0; ungoverned import without the extra; the refined corrects grammar.

Working claim:
> Part 2a adds approved-only import through `review_state` with the live sha256 checked against `approved_sha256`, identity and idempotency by page key and revision, stale pages keeping their last approved memory, the `corrects` grammar, and reconciliation that supersedes corrected memories (provenance kept, unknown references reported), with one floor of 0.7.0 for import and export and today's file-reading import kept, labelled ungoverned, when wiki-studio is absent. Its acceptance test is wiki-studio's own Release B loop test. Withdrawal and sync state (2b) and governed mode and curation debt (2c) are deferred, not dropped.

Mismatches:
  - none. The amendment records the owner's two decisions of 2026-10-27 on the review of #60: corrects are reconciled on every import of an approved page (FR-015), and already-current pages are reported under `unchanged` (FR-016). Scope unchanged.

Verdict: aligned
Confidence: high

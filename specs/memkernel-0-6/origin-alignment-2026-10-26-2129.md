# Origin alignment check — memkernel-0-6 (Release B wiki bridge, part 1)

Origin: https://github.com/gosha70/memkernel/issues/48 (and its owner-decision comments of 2026-10-24 and 2026-10-25), https://github.com/gosha70/wiki-studio/issues/38, wiki-studio's Release B pitch, and specs/memkernel-0-6/origin/2026-10-26-release-b-start.md.

Origin claim:
> Close the memkernel side of wiki-studio's Release B (memkernel #48): remove the bridge's whole-wiki snapshot and rollback and scaffold through wiki-studio's api.init, pass the combined integration gate, then import approved revisions only and reconcile corrected memories once wiki-studio 0.7.0 provides review state.

Working claim:
> Part 1 removes `_WikiSnapshot`, scaffolds a missing index and log through `api.init` on the gated path, requires wiki-studio >= 0.6.0 for the gate (refusing older installs), pins 0.6.0 in the dev lock, records the proposal name and submission digest from the promote receipt, documents the lock file, and adds compatibility, concurrency, forced-failure and old-version tests against the real wiki-studio. Part 2 (approved-only import, corrects, withdrawal, governed mode) is deferred until wiki-studio 0.7.0's API exists. Nothing merges before memkernel's v0.5.0 tag.

Mismatches:
  - none. The origin's own schedule puts snapshot removal first and approved-only import later; part 2 is deferred, not dropped.

Verdict: aligned
Confidence: high

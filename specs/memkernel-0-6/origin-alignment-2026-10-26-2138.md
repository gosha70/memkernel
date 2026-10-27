# Origin alignment check — memkernel-0-6 (Release B wiki bridge, part 1), after the wiki-studio review

Origin: https://github.com/gosha70/memkernel/issues/48 (and its owner-decision comments of 2026-10-24 and 2026-10-25), https://github.com/gosha70/wiki-studio/issues/38, wiki-studio's Release B pitch, and specs/memkernel-0-6/origin/2026-10-26-release-b-start.md.

Origin claim:
> Close the memkernel side of wiki-studio's Release B (memkernel #48): remove the bridge's whole-wiki snapshot and rollback and scaffold through wiki-studio's api.init, pass the combined integration gate, then import approved revisions only and reconcile corrected memories once wiki-studio 0.7.0 provides review state.

Working claim:
> Part 1 removes `_WikiSnapshot` (a failed export may leave the scaffold `api.init` created; disclosed), scaffolds a missing index and log through `api.init` on the gated path (wiki-studio's scaffold differs from memkernel's; disclosed in the CHANGELOG), requires wiki-studio >= 0.6.0 for the gate, pins 0.6.0 in the dev lock, records the proposal name, submission digest and archive location from the receipt where it actually is (including "promoted, not archived" when wiki-studio's archive step fails), documents the lock file, and adds compatibility, concurrency, forced-failure, old-version and archive-failure tests against the real wiki-studio. Part 2 is deferred until wiki-studio 0.7.0. Nothing merges before memkernel's v0.5.0 tag.

Mismatches:
  - none. The changes since the previous record (FR-001 residue, FR-002 visible scaffold difference, FR-005 receipt location and archive failure, SC-6) refine part 1's existing requirements against wiki-studio 0.6.0's actual behaviour; scope is unchanged.

Verdict: aligned
Confidence: high

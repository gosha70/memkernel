# Origin alignment check — memkernel-0-6, after the re-review of FR-009

Origin: https://github.com/gosha70/memkernel/issues/48 (and its owner-decision comments of 2026-10-24 and 2026-10-25), https://github.com/gosha70/wiki-studio/issues/38, wiki-studio's Release B pitch, specs/memkernel-0-6/origin/2026-10-26-release-b-start.md, and specs/memkernel-0-6/origin/2026-10-27-committed-then-failed.md.

Origin claim:
> Close the memkernel side of wiki-studio's Release B (memkernel #48): remove the bridge's whole-wiki snapshot and rollback and scaffold through wiki-studio's api.init, pass the combined integration gate, then import approved revisions only and reconcile corrected memories once wiki-studio 0.7.0 provides review state. (2026-10-27) Detect an export wiki-studio committed and then failed, from wiki-studio's receipt, and report it as written with the "promote again" hint; never retry automatically.

Working claim:
> Part 1 as before (snapshot removed, scaffold through `api.init`, floor 0.6.0, receipt fields and the archive hint, response keys, tests against the real wiki-studio), plus FR-009/SC-7: when the gate raises after `propose`, memkernel checks the receipt left in the proposal directory (state committing/committed) and each created page's on-disk sha256 against the receipt's `post_sha256`, treating a missing receipt as no commit and falling back to a content comparison only when the receipt exists but cannot be read; a confirmed commit is reported as written with `archived_dir` null and the finishing hint, otherwise `gate_error`. The archive hint uses absolute paths. Part 2 is deferred. Nothing merges before memkernel's v0.5.0 tag and #54.

Mismatches:
  - none. FR-009 implements the owner's decision of 2026-10-27 (receipt hash check first, content fallback only for a receipt that cannot be read, no automatic retry); a missing receipt is no commit, following the decision's own premise and wiki-studio's rule, after a reproduced false positive.

Verdict: aligned
Confidence: high

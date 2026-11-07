# Origin alignment check — memkernel-0-8-untrusted-memory, the US1 build

Origin: the approved spec (#105) and the owner's message of 2026-11-06: "go: merge #105 (merge commit) once CI is
green, and build #85 as its own PR for review."

Working claim:
> lifecycle.py quotes stored text in `<stored-memory kind=…>` elements (checkpoint, context, candidates, review
> sources, curation-debt pages), neutralises `<\s*/?\s*stored-memory` case-insensitively, adds one notice per block
> after truncation, and keeps elements whole in `_cap`; on_post_compact gets the same treatment and the checkpoint
> share. templates/claude-settings.example.json carries the four Edit deny rules, checked live with Claude Code
> 2.1.319; README and CHANGELOG.

Mismatches:
  - U3's notice wording changed: the confirmed text writes a literal `<stored-memory>`, an opening tag that never
    closes. Recorded in spec.md as a build amendment awaiting the owner.
  - U1 lists a review item's "source path and reason": only the source is quoted, because the reason is memkernel's
    own constant (REVIEW_REASON_MISSING / REVIEW_REASON_CHANGED), which U1's rule keeps outside.

Verdict: aligned
Confidence: medium

# Origin alignment check — memkernel-0-6-compaction-hooks (#68)

Origin: https://github.com/gosha70/memkernel/issues/68, https://github.com/gosha70/memkernel/issues/59, https://code.claude.com/docs/en/hooks and specs/memkernel-0-6-compaction-hooks/origin/2026-10-29-issue-68.md.

Origin claim:
> Fix D1–D4 of #59 (#68): no placeholder checkpoint, recovery through SessionStart(compact) rather than PostCompact's output, keep compact_summary, branch SessionStart on source; confirm the payload field names against the current hooks reference first; spec before code. The owner's go: "go: spec for #68".

Working claim:
> PreCompact retains nothing without a summary; PostCompact retains compact_summary as a tagged checkpoint and prints nothing; SessionStart gives the full block on startup, clear or no source, a recovery block on compact that leaves out compact-summary checkpoints and runs no consolidation, and nothing on resume or fork. The library's existing methods keep their behaviour. The 0.3 stdout contract is amended, the README and memory-tiers.md corrected, a CHANGELOG entry added; the lifecycle suite is unaffected. Field names confirmed against the reference on 2026-10-29.

Mismatches:
  - none. Two additions follow from the reference rather than from #68: `fork` is treated like `resume`, and the recovery block is built so it does not depend on the undocumented order of PostCompact and SessionStart(compact). Scope stays D1–D4; D5–D9 remain in #59.

Verdict: aligned
Confidence: high

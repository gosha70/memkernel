# Origin alignment check — memkernel-0-10-recall-log, review amendment A2

Origin: gosha70/memkernel#120 (origin/2026-11-11-issue-120.md), with the counting rule from #112.

Origin claim: as in origin-alignment-2026-11-11-1300-draft.md.

Working claim:
> As A1, with A2 from the review of #124: on_post_compact logs only with a session id; an oversized record is cut
> to fit the size limit; the log is POSIX-locked, with one warning on Windows; the count evaluates every logged
> filter, separates MCP recalls from hook blocks in a miss's evidence, and counts each session once.

Mismatches:
  - none against the origin. #120 asks for a bounded log; A2 makes the bound hold for one record too. The Windows
    scope matches the store locks' documented policy.

Verdict: aligned
Confidence: high

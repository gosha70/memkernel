# Origin alignment check — memkernel-0-10-recall-log, after DeepSeek round 1

Origin: gosha70/memkernel#120 (origin/2026-11-11-issue-120.md), with the counting rule from #112.

Origin claim: as in origin-alignment-2026-11-11-1300-draft.md.

Working claim:
> As the draft, with the review's precisions: the log file is 0600 and keeps queries up to 2,000 characters; a write
> failure is logged once per process; rotation is checked before each append; D2 pairs records one to one and calls
> multi-session matches ambiguous; D5 takes the marker-carrying backtick spans; D6's retrieval miss counts only
> recalls before the failure and says whether filters excluded the memory; FR-007 lists the README's limits.

Mismatches:
  - unchanged from the draft record (transcripts instead of the spool; D1 leaves library callers unlogged, the
    owner's decision; SC-3 adds cases). The review fixes narrow the rules; none moves away from #120.

Verdict: aligned
Confidence: medium

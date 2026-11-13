# Origin alignment check — memkernel-0-10-recall-log, second review of #124

Origin: gosha70/memkernel#120 (origin/2026-11-11-issue-120.md), with the counting rule from #112.

Origin claim: as in origin-alignment-2026-11-11-1300-draft.md.

Working claim:
> As A2, with the second review's fixes: records keep query_sha256 and pair by it; a truncated record cuts query text
> first, then trailing ref_ids, and makes a miss unknown; include_needs_review is not judged.

Mismatches:
  - none against the origin. #112's rule classifies by what the session could see; a cut-down record cannot show
    that, so unknown is the faithful outcome.

Verdict: aligned
Confidence: high

# Origin alignment check — memkernel-0-15-harness-foundations, after the review of #143

Origin: #119 and the review the owner passed on (origin/2026-11-18-issue-119.md, last section).

Origin claim: as in plan.md.

Working claim:
> As drafted, plus: scope applies on every read path and through promotion (a promoted record keeps its source's
> scope), stated as a convention between cooperating callers, not security; the abstention reason goes into the
> recall log's receipt, leaving MCP recall's JSON list unchanged (the review's second option, since a field next to
> the results would change the list into an object).

Mismatches:
  - none. #119 asks for "isolation of private or temporary agent memory" and "compatibility with existing MemKernel
    consumers"; both now hold on every path. D1–D6 remain proposed for the owner.

Verdict: aligned
Confidence: high

# Origin alignment check — memkernel-0-13-one-store-across-tools, the security fact corrected

Origin: #107, its comment, and the review the owner passed on (origin/2026-11-18-issue-107.md).

Origin claim: as in plan.md.

Working claim:
> As after the review, with one fact corrected: the SDK already protects a loopback HTTP bind; only non-loopback
> binds lacked a host/origin check. That fix ships on its own (#149, for #148), with the allowed hosts following
> MEMKERNEL_HOST; this spec relies on it.

Mismatches:
  - none.

Verdict: aligned
Confidence: high

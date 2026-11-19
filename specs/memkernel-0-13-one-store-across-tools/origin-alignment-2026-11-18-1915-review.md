# Origin alignment check — memkernel-0-13-one-store-across-tools, after the review of #141

Origin: #107 and its comment; the review the owner passed on (origin/2026-11-18-issue-107.md, last section).

Origin claim: as in plan.md.

Working claim:
> As drafted, plus: the HTTP transport runs with the SDK's host and origin checks (local only, no authentication),
> which applies to today's transport too; session-start writes no spool line for any format, and maps Codex's
> source values one to one (Cursor and Antigravity get startup); Codex's cap is 6,000 characters, with the
> arithmetic shown; the #139 fix is on main.

Mismatches:
  - none. The owner's scope (local, self-hosted, one developer) is what "local only" enforces. D1–D5 remain
    proposed for the owner.

Verdict: aligned
Confidence: high

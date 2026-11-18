# Origin alignment check — memkernel-0-13-one-store-across-tools, the draft spec

Origin: gosha70/memkernel#107 and its comment (origin/2026-11-18-issue-107.md); #139 for the cross-process fact.

Origin claim: as in plan.md.

Working claim:
> FR-001–FR-005: several stdio servers on one store supported (after #140) with a two-server test; one shared HTTP
> server documented with each tool's registration and a two-client test; `memkernel session-start --format` for
> tools' hooks; templates for Codex, Cursor and Antigravity, a hook only where the tool's hook is documented and
> reliable (D3); README and CHANGELOG. Local and self-hosted, no hub.

Mismatches:
  - none. #107 item 1's test overlap with #95 is already met (the real transport tests exist); the spec adds the
    two-client case. D1–D5 are proposed and await the owner.

Verdict: aligned
Confidence: high

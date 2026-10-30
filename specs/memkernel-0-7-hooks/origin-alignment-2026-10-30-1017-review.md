# Origin alignment check — memkernel-0-7-hooks, after the review of #77

Origin: as in the previous record, plus specs/memkernel-0-7-hooks/origin/2026-10-30-review-77.md.

Origin claim:
> Rework H1 (no floor against the fixed generic queries; startup context by type/importance/recency, the checkpoint text at compact, or calibrate on the hooks' real queries); H2 only with checkpoint_only; confirm H3; H4's rule "no checkpoint during that session" (session id on agent checkpoints or the session start recorded), spool in the same state dir; 2c must fit D7's budget.

Working claim:
> H1: no floor against the fixed queries; startup context by type, importance and recency without a query; compact context recalled with the latest own checkpoint's text; a calibrated floor deferred to #59. H2: order="newest" accepted only with checkpoint_only=true. H3 confirmed. H4: the SessionStart hook records a started line and SessionEnd an ended line in MEMKERNEL_STATE_DIR's spool; a session is flagged only when no checkpoint falls inside its window and no compact summary carries its id. 2c's curation debt is a named share of the 9,000-character budget.

Mismatches:
  - none. Of the review's two H4 means, recording the session start is used, because agents' checkpoints cannot carry Claude Code's session id (the MCP server never sees it).

Verdict: aligned
Confidence: high

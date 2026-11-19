# Origin alignment check — memkernel-0-14-capture-signals, the build

Origin: #147, #59, the owner's D8 for S2, the reviews the owner passed on, and the owner's approval
(origin/2026-11-18-59-s3.md).

Origin claim: as in plan.md (#147).

Working claim:
> Built as approved: the reader's structured AskUserQuestion answers and full tool input (FR-001); owner answers as
> episodes, keyed by call and question index, the last 30 per session (FR-002, D2, D3, D5); one session outcome from
> create and merge calls only, matched by GitHub URL shape, a merge's URL from its input, edited files up to 10 then a
> count (FR-003, D4); per-extractor caps (FR-004); up to 2 answers among the promotion candidates (FR-005, D6);
> per-extractor counts in the report (FR-006); README and CHANGELOG (FR-007); at most 3 captured records per origin
> session in one recall result (FR-008, D7).

Mismatches:
  - none in scope. Three build details, stated in the PR: CAPTURE_ANSWER_CANDIDATES lives in core/models.py (core
    applies it and imports no adapter), with capture.ANSWER_CANDIDATES as its alias; the owner's own words keep up to
    600 characters (ANSWER_TEXT_MAX), where commands keep 300; outcome detection does not require the command's own
    exit status, since a URL in the result is the evidence (a piped `gh issue create ... | tail -1` counts). The
    GitHub MCP shapes are tested from the documented shapes: no local transcript holds a GitHub MCP call.

Verdict: aligned
Confidence: high

# Origin alignment check — memkernel-0-13-one-store-across-tools, the build

Origin: #107, its comment, the reviews the owner passed on, and the owner's decisions (origin/2026-11-18-issue-107.md).

Origin claim: as in plan.md.

Working claim:
> Built as approved: two stdio servers on one store, tested with real processes (FR-001, D1); one HTTP server with
> two clients, tested, and the README section (FR-002); memkernel session-start with plain, cursor and antigravity
> formats, --max-chars keeping headings, the stored-memory notice and whole elements, no spool line, source mapped
> (FR-003, D2); templates for Codex (config, AGENTS.md, a SessionStart hook with --max-chars 6000), Cursor and
> Antigravity (config, an always-on rule), each over stdio or HTTP (FR-004, D3, D4, D5); README and CHANGELOG
> (FR-005). The host and origin checks shipped earlier (#149).

Mismatches:
  - none. Build details stated in the PR: session-start exits 0 and prints nothing (or {} for the JSON formats) when
    memkernel fails, so the tool's session still starts; a session id is read from session_id, conversation_id or
    conversationId; the stored-memory notice survives a cut.

Verdict: aligned
Confidence: high

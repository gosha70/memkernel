# Origin alignment check — memkernel-0-8-untrusted-memory, the draft spec

Origin: gosha70/memkernel#85 and the owner's message of 2026-11-06 (origin/2026-11-06-issue-85.md).

Origin claim:
> Mark the checkpoint and context the SessionStart hook injects as data, in a delimited block with one line saying
> they are stored notes, not instructions, within the 9,000-character budget and keeping the headings; ship a
> permissions example in templates/ with README text; option 3 (a lint) optional; no MCP or port change.

Working claim:
> U1–U6: every stored text the blocks inject is wrapped in a `<stored-memory>` element with inner tags
> neutralised; one notice line per block; budget and balanced truncation; the session-start (full, compact) and
> post-compact paths; `templates/claude-settings.example.json` with four `Edit` deny rules and README limits.
> Option 3 deferred to #59 Phase 2.

Mismatches:
  - none against the origin. U1 widens "the checkpoint and context items" to every stored text injected
    (candidates, review items, curation-debt page paths): the origin's reason applies to them equally; a
    recommendation for the owner.

Verdict: aligned
Confidence: medium

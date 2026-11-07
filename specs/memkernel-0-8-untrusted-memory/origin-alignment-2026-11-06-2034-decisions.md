# Origin alignment check — memkernel-0-8-untrusted-memory, the owner's decisions

Origin: as before, plus the owner's message of 2026-11-06: "go: push the #85 spec as a spec-only PR. I confirm U1,
U3, U4, U5. U2: escape only the tag itself (<stored-memory / </stored-memory, any case), never every <. U6: deny
.memkernel/**, .claude/settings.json, .claude/settings.local.json and the hooks directory, not all of .claude/."

Working claim:
> spec.md records U1, U3, U4, U5 as confirmed; U2 escapes only the tag, case-insensitively, leaving every other `<`;
> U6 denies Edit(/.memkernel/**), Edit(/.claude/settings.json), Edit(/.claude/settings.local.json) and
> Edit(/.claude/hooks/**). SC-2 covers mixed case and an untouched `<`.

Mismatches:
  - none.

Verdict: aligned
Confidence: high

---
feature_id: memkernel-0-13-one-store-across-tools
spec_mode: full
status: approved
date: 2026-11-18
collaboration_mode: single
origin:
  issue: gosha70/memkernel#107
  urls:
    - https://github.com/gosha70/memkernel/issues/107
    - https://github.com/gosha70/memkernel/issues/139
  transcripts:
    - specs/memkernel-0-13-one-store-across-tools/origin/2026-11-18-issue-107.md
  origin_claim: |
    "One memkernel store across several coding tools (Claude Code, Codex, Cursor, Antigravity)." The goal is one
    correct record across tools, not better recall than a shared file: one shared server documented and tested;
    session-start context in the other tools, by hook or by instruction, checked against each tool's current docs; a
    tested answer, supported or documented as unsupported, for several stdio servers on one store. The owner's scope
    (#107 comment, 2026-11-08): one developer using several coding tools on the same machine; memkernel stays
    self-hosted and local, and no session data leaves the machine.
---

# Plan: one memkernel store across several coding tools (#107)

## Approach

1. **Several stdio servers on one store: supported**, on top of the #139 fix (on `main` since #146), with a two-server test.
2. **One shared HTTP server:** a README section with each tool's registration snippet, and a two-client test.
3. **`memkernel session-start`:** a subcommand that prints the startup block in a tool's hook output shape.
4. **Templates** for Codex, Cursor and Antigravity: an MCP registration snippet, an instruction file, and a
   session-start hook where the tool's hook is reliable.
5. **Docs:** README "One store across tools"; CHANGELOG.

## Risks

- The other tools' hook formats are undocumented in places (Antigravity's `injectSteps` shape, Cursor's output
  mapping) and change between versions; the spec only ships a hook where the format is documented and consistent.
- Live checks in Codex, Cursor and Antigravity need paid sessions; the build checks each template's file format, and
  the README states which tool versions the templates follow.

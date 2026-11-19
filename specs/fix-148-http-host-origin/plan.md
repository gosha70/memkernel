---
feature_id: fix-148-http-host-origin
spec_mode: none
status: draft
date: 2026-11-18
collaboration_mode: single
origin:
  issue: gosha70/memkernel#148
  urls:
    - https://github.com/gosha70/memkernel/issues/148
  transcripts:
    - specs/fix-148-http-host-origin/origin/2026-11-18-issue-148.md
  origin_claim: |
    "Security: the HTTP transport has no Host/Origin check (DNS rebinding) and no authentication." Turn the SDK's
    host and origin checks on, the allowed names following MEMKERNEL_HOST; a wildcard bind needs a new
    MEMKERNEL_ALLOWED_HOSTS, and without it keeps today's behaviour with a warning; the README says local only, no
    authentication; a Security entry in the CHANGELOG.
---

# Plan: the HTTP transport's Host/Origin check follows MEMKERNEL_HOST (#148)

A security fix (spec_mode none). Corrected scope: the SDK already protects a loopback bind; the fix covers
non-loopback binds and adds `MEMKERNEL_ALLOWED_HOSTS`.

## Change
- `memkernel.mcp.server.transport_security(settings)`: loopback keeps the SDK's names (`127.0.0.1`, `localhost`,
  `[::1]`); a specific address allows itself, with a warning; a wildcard bind allows `MEMKERNEL_ALLOWED_HOSTS`, or
  runs unchecked with a warning when it is empty; the allowed origins follow the same names (http and https).
- `run_server` passes it to the Streamable HTTP transport. `MEMKERNEL_ALLOWED_HOSTS` (comma-separated) in settings.
- README (the setting; "local only, no authentication"); CHANGELOG under Security.

## Tests
- Unit: the names and warnings per bind (loopback, IPv6 loopback, a specific address, wildcard with and without
  allowed hosts).
- E2E: a real server on loopback refuses a foreign Host (421) and Origin (403) and still serves a client; it
  guards the loopback default against regression (it passed before the change too, the SDK's own protection).

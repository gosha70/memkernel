# Origin transcript — memkernel-0-4 (2026-10-12)

User, after issue #3 was closed as superseded and #9 / #10 were filed:

> So can start working on these 2?

Decisions taken through the plan-phase clarification (user's picks):

1. **Bundle / version** — "One bundle, version 0.4.0": `specs/memkernel-0-4` with revalidation, the health pass and release hygiene; semver minor; the roadmap's "ecosystem" 0.4 becomes 0.5.
2. **Revalidation trigger** — "consolidate(revalidate=...) + session start": `MemoryService.revalidate()` as a Python method; `consolidate` gains a `revalidate` flag that `MemoryLifecycle.on_session_start` sets; the consolidate MCP tool exposes the flag; the admin API gets an endpoint. No new MCP tool (nine of ten slots used, ceiling exclusive).
3. **Stale code memories on re-retain** — "Auto-supersede by source": `retain(type=code, source=X)` supersedes the previous live code memory for X so recall never returns both.
4. **Health exposure** — "Also fold counts into consolidate()": `MemoryService.health()`; `GET /health/store`; a counts summary in the `memory://status` resource; the consolidate report carries the summary so the session-start hook prints it.

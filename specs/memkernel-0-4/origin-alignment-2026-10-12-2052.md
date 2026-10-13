# Origin alignment check — memkernel-0-4

Origin: https://github.com/gosha70/memkernel/issues/9 and https://github.com/gosha70/memkernel/issues/10 (both read in full this session), with the user's plan-phase decisions in specs/memkernel-0-4/origin/2026-10-12-decisions.md; issue #3's closing comment records the deliberate non-choices.

Origin claim:
> Start working on the two issues left after closing #3 as superseded: #9 revalidate `code` memories when their source changes (mark `needs_review`, exclude from default recall, supersede on re-retain, no LLM or new dependency, plain file hashing) and #10 a deterministic, LLM-free store health pass (orphans, dangling links, stale sources, near-duplicates, expired-but-present; read-only, no new MCP tool). Ship both as one bundle, version 0.4.0; run revalidation through consolidate(revalidate=...) and at session start; auto-supersede code memories by source; expose health through Python, the admin API, the status resource and the consolidate report.

Working claim:
> spec.md delivers four user stories: (US1) `MemoryService.revalidate()` compares each live canonical `code` memory's file hash with its `content_hash` under a new `project_root` setting, flags `needs_review` with reason `changed` or `missing` (clearing it when the file matches again), propagates to chunk records, excludes flagged memories from `recall` unless `include_needs_review=True`, runs from `consolidate(revalidate=True)`, from `MemoryLifecycle.on_session_start()` (new `### Needs review` section only when non-empty) and from `POST /revalidate`; (US2) chunk records of `code` memories are tagged `code_chunk`, and `retain(type=code, source=X)` with changed content supersedes the previous live canonical for `X` and deletes its chunk records, keeping the old canonical as a superseded record while identical content still dedups; (US3) a read-only `health(full=True)` returning `HealthReport` with orphans, dangling links, stale sources, needs-review, expired-but-present and, in full mode only, near-duplicates (re-embedded, bounded by settings), exposed as `GET /health/store`, as a counts summary in `memory://status` and in the `consolidate()` report, and as a `### Store health` line at session start; (US4) version 0.4.0, CHANGELOG, README, roadmap (ecosystem relabelled 0.5), memory-tiers.md and the CLAUDE.md template. No new dependency, no git calls, no new MCP tool, no `--fix` mode, no warm/cold tiers or route hints.

Mismatches:
  - none

Verdict: aligned
Confidence: high

Notes:
  - #10 lists "near-duplicates" as a candidate source for `supersedes`; the spec reports pairs only (read-only), matching #10's own "read-only here" wording.
  - #9 mentions "the git blob at the recorded commit when one is stored" as an option; the spec chooses file hashing only (plan ADR-1), which #9 also allows ("content hash of the file").

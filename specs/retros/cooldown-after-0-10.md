# Cooldown after the 0.10 cycle (2026-11-15)

## Shipped on `main`, not yet released
`[Unreleased]` in `CHANGELOG.md` holds four entries:
- decision records in the agent template, with `top_k=5` lookups (#57, #118, #121);
- the recall log and the repeated-mistake count (#120, #124);
- revalidation of decisions that cite files, returned flagged (#123, #127).

Dependencies: opentelemetry 1.45.2 (#125).

## Defects fixed in review this cycle
- #124: oversized records, truncation that proved nothing, cut queries that could not pair, a quadratic fit, ambiguous records lost, malformed lines trusted, `shown_without_repeat` counting pairs, hook records using the lifecycle's settings, an unattributable post-compact record.
- #127: the `order="newest"` path, flagged items unmarked in hook context lines, a hashless decision clearing any flag, durable flags missing from the startup list.

## Ready next
| Item | Size | State |
|---|---|---|
| Release 0.10.0 | small | a release PR (versions, CHANGELOG date), then the owner tags |
| Reply on #112 with the count script | small | after the tag, so the link is a release |
| #59 Phase 2 | large | sliced into S1 anti-rot injection (#128, spec approved), S2 capture core, S3 more signals |
| #107 one store across tools | large | needs a spec; tool docs to check |
| Decision records in the Kiro steering file and code-copilot-team's skill | small | outside #57's scope; not filed |
| Local cleanup | small | redundant lock-fix branch, merged worktrees, #85 test folders; each on the owner's go |

## Decided this cooldown (2026-11-15)
- CI runs `mypy --strict` on the maintained eval tools, listed explicitly (retro action 5): PR #129.
- #59 Phase 2 decisions D1–D5 accepted; S1 filed as #128, its spec approved (not yet committed).

---
spec_mode: full
feature_id: memkernel-0-5
risk_category: feature
justification: "Two tracks across docs, packaging (first optional extra, ADR-010), the wiki bridge, a new eval/lifecycle-suite tree and a paid calibration and measured run; a full spec keeps both tracks bounded and the evidence claims honest."
status: draft
date: 2026-10-15
collaboration_mode: single
origin:
  issue: gosha70/memkernel#17
  urls:
    - https://github.com/gosha70/memkernel/issues/17
    - https://github.com/gosha70/wiki-studio
    - https://github.com/gosha70/wiki-studio/blob/v0.1.0/docs/consumers.md
    - https://github.com/gosha70/wiki-studio/issues/10
    - https://github.com/gosha70/wiki-studio/tree/v0.4.0/docs/agent-arm
  transcripts:
    - specs/memkernel-0-5/origin/2026-10-15-decisions.md
    - specs/memkernel-0-5/origin/2026-10-16-option-b.md
    - specs/memkernel-0-5/origin/2026-10-17-wiki-studio-arm.md
    - specs/memkernel-0-5/origin/2026-10-18-wiki-studio-0-4-1.md
  origin_claim: |
    Show strong evidence of how memkernel helps with memory and context
    management, and state clearly what it is and what it is not (it is not a
    token optimizer). Adopt wiki-studio as the wiki maintainer where the
    current release is sufficient (lint and health, shared schema) and
    specify what wiki-studio must expose for the rest (promote gate, schema
    as code). Finalize the positioning and the wiki-studio contract before
    the first benchmark run; let the #17 protocol proceed in parallel.
---

# Implementation Plan: memkernel 0.5 — evidence and wiki-studio

**Branches**: `feature/memkernel-0-5-us1` (US1, released as 0.4.1), `feature/memkernel-0-5-us2` (US2 tasks 5–8, merged), one branch per later phase (US2 tasks 9–10, US3, US4); US5 lives upstream
**Input**: specs/memkernel-0-5/spec.md

## Summary

Two tracks, one release train.

Track A (wiki-studio). memkernel and wiki-studio already share one page
schema, verified against wiki-studio 0.1.0 on 2026-10-15 (export of three
memories lints clean). memkernel adopts wiki-studio as the owner of that
schema, of the lint and health pass, and of the only write into the wiki
(the promote gate), through an optional `memkernel[wiki]` extra with a
decision record (ADR-010). memkernel does not adopt wiki-studio's ingest or
query backends: they shell out to a copilot CLI, and memkernel runs inside
that CLI. Steps that need wiki-studio changes (a public proposal API, a
schema-as-code module) wait for wiki-studio 0.2.0 and are listed as a
companion deliverable.

Track B (evidence, issue #17), amended 2026-10-16 to option B. Task 11
showed that `agent-memory-bench` at `c1b15726` cannot run the lifecycle
scenarios (sequence mode carries only the memory store, so the files-only
controls carry nothing; no second-namespace session; no compaction control)
and cannot yet run a memkernel retrieval arm (missing relay, harness edits
to register an arm, HTTP hosting behind the broker, untested Claude route).
The evidence for the lifecycle claims therefore comes from a **maintainer-run
supplemental evaluation**: a minimal stdlib runner in `eval/lifecycle-suite/`
that orchestrates the four lifecycle groups only, on tasks in the
benchmark's executable task format, with seven arms (the seventh,
`wiki_studio`, on `lc-wiki` only) whose persistence rules
are frozen and identical in what each arm is told and allowed to save. A
credential-free demonstration with simulated events comes first; a
calibration run on a Claude model proves live compaction and fixes the
budget, and its outcomes are never reported as results; then a
preregistered, announced, freeze-verified measured run. Entering memkernel
as a retrieval arm of the benchmark continues upstream (US5) and is not a
release gate; its results, if any, are reported separately.

Release train: 0.4.1 (released 2026-10-15) = positioning docs, wiki-studio
rename, CI contract test and the #15 `.env` fix. 0.5.0 = the extra and lint
feedback on `wiki_export` (the gate as far as wiki-studio 0.2 allows), the
lifecycle suite and its report.

## Technical Context

**Language/Version**: Python 3.11–3.13, Poetry, pydantic 2, FastMCP (`mcp` 1.x), ChromaDB 1.5; wiki-studio ≥ 0.2 (stdlib-only) as an optional extra
**Primary Dependencies**: `src/memkernel/wiki/{sync,pages,studio}.py`, `src/memkernel/mcp/tools/wiki.py`, `pyproject.toml`, `docs/adr/ADR-010-*.md`, `eval/lifecycle-suite/**` (runner, arms, tasks, oracles, records, diagnostics, secret scan, report, preregistration, results), `eval/check_freeze.py`, `tests/unit/test_{wiki,wiki_studio,lifecycle_arms,lifecycle_suite,lifecycle_demo,lifecycle_records,check_freeze}.py`; `.github/workflows/ci.yml` is not touched
**Testing**: fast suite as in 0.4; wiki-studio tests as merged in US2; lifecycle references, the demonstration, the persistence-rule test, records and secret-scan fixtures and the freeze verifier run in CI on Python 3.11 with no model call
**Constraints**: no new *required* runtime dependency; MCP tool count stays nine; no subprocess to a copilot CLI from inside the server; the lifecycle runner is stdlib-only, four groups only, and never runs the retrieval grid; no paid run in CI; no LLM judge; no claim about token savings beyond measured usage

## Constitution Check

| Rule file | Concern | Status |
|-----------|---------|--------|
| `coding-standards.md` | No magic strings; thresholds in config, not code | OK — thresholds live in `preregistration.md`; persistence rules and instruction bytes live in each arm's `config.frozen.json` |
| `safety.md` | Isolation and data handling of live runs | OK — fresh workspace, `HOME` and config dir per session under a run root outside the checkout; receipts only in the repo; secret scan and operator review gate every commit of results |
| `copilot-conventions.md` | Scope proportional to the claim; reuse before build | OK — the runner is bounded to the four groups and reuses the benchmark's task format; the reversal of the 2026-10-15 constraint is recorded with its evidence |
| project `CLAUDE.md` | New dependency needs an ADR; tool count < 10 | OK — ADR-010; `wiki_export` grows a report, no tool added |

## Cross-repository sequence

| # | Repo | Deliverable | Depends on | Unblocks |
|---|------|-------------|------------|----------|
| 1 | memkernel | 0.4.1: positioning docs, `ai-wiki` → wiki-studio, CI contract test (US1) | — | first benchmark run (frozen integration) |
| 2 | wiki-studio | 0.2.0: `api.propose(...)` + documented patch-set format, `wiki_studio.schema` module (page types → dir, required sections), `consumers.md` recipe fix | — | US2 |
| 3 | memkernel | 0.5.0 US2: `[wiki]` extra, ADR-010, lint feedback and promote gate in `wiki_export`, schema contract test | 1, 2 | `lc-wiki` group of the lifecycle suite |
| 4 | memkernel | 0.5.0 US3: lifecycle runner, arms, tasks, demonstration, records, secret scan, freeze verifier | 1 | US4 |
| 5 | memkernel | 0.5.0 US4: calibration, preregistration, measured run, report, release | 3, 4 | README evidence link |
| 6 | agent-memory-bench | answers to the integration questions; then a memkernel retrieval arm (US5) | owner posts the questions | separate retrieval report (not a release gate) |

The #17 contributor's protocol text, if it arrives, is folded into the
preregistration; the runner, suite and run stay with the maintainers.

## Phase plan

- **US1** (0.4.1) — done, released 2026-10-15.
- **US2** (0.5.0) — tasks 5–8 done (PR #21); tasks 9–10 (promote gate,
  schema contract test) need wiki-studio 0.2.0 and move to 0.5.1 if it slips.
- **US3** (0.5.0) — independent of US2; starts after this amendment merges.
- **US4** (0.5.0) — after US2 and US3; the only phase that spends money.
  Sequence: calibration (outcomes excluded), freeze tasks and arm
  configurations, merge, set the version to `0.5.0rc1` (code-freeze SHA),
  commit the preregistration alone, push it and announce it on #17, measured
  run, commit receipts and the report, bump to `0.5.0`, verify with
  `check_freeze.py`, tag; roadmap ticks only after the tag.
- **US5** — upstream, whenever its maintainers answer; never a gate.

## Risks

- wiki-studio 0.2.0 timing: mitigated by the US2 fallback above.
- Credibility of an own runner: the lifecycle numbers come from a runner
  memkernel's maintainers wrote. Mitigations: bounded scope (FR-011), the
  benchmark's task format and executable checkers, frozen per-arm rules with
  a test, a public preregistration announced before the run, the freeze
  verifier, receipts anyone can recompute, the "maintainer-run supplemental
  evaluation" label, and failures and nulls published.
- Live compaction may not be producible in a `-p` session within a
  reasonable budget; calibration decides, and `lc-compact` is dropped with a
  statement if it cannot be shown (FR-015).
- Exposure fairness: an arm's instruction can coach the agent beyond
  persistence; the `protocol` and `placebo` arms separate instruction effects
  from memory effects, and instruction bytes are frozen and published.
- Run cost: the formula and the 2026-10-15 prices are in the task 11 research
  note (section 11); per-session usage is measured by calibration, never
  taken from another model's ledger, and the preregistration carries the
  budget.
- Upstream (US5) may not answer before 0.5.0; it is not a gate, and no
  retrieval claim is made without it.
- Data: raw streams never enter the repository; receipts, a secret scan and
  operator review gate every commit of results (FR-018).

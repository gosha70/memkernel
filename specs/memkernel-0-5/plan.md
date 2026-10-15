---
spec_mode: full
feature_id: memkernel-0-5
risk_category: feature
justification: "Two tracks across docs, packaging (first optional extra, ADR-010), the wiki bridge, a new eval/agent-benchmark tree and a paid pilot run; a full spec keeps both tracks bounded and the evidence claims honest."
status: draft
date: 2026-10-15
collaboration_mode: single
origin:
  issue: gosha70/memkernel#17
  urls:
    - https://github.com/gosha70/memkernel/issues/17
    - https://github.com/gosha70/wiki-studio
    - https://github.com/gosha70/wiki-studio/blob/v0.1.0/docs/consumers.md
  transcripts:
    - specs/memkernel-0-5/origin/2026-10-15-decisions.md
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

**Branches**: `docs/what-memkernel-is-not` (US1, released as 0.4.1), `feature/memkernel-0-5` (US2–US4, released as 0.5.0)
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

Track B (evidence, issue #17). memkernel enters `agent-memory-bench`
(GiulioDER/agent-memory-bench, Apache-2.0, pinned by commit): a public,
preregistered benchmark that runs Claude Code on repository tasks, grades by
executable checkers with no LLM judge, pairs cells by task, seed and fixture,
and ships its own control arms (`bare`, `claude_md`, `placebo`, `protocol`,
`fs_grep`). memkernel contributes a reviewable adapter with a frozen
configuration, and a supplemental suite in the benchmark's task format for
the four lifecycle claims the public grid does not measure (retain across
sessions, compaction recovery, revalidation after a repository change, wiki
sharing). One preregistered run on a Claude model is published with 0.5.0,
nulls and discarded cells included. Nothing of the harness is reimplemented.

Release train: 0.4.1 = positioning docs + wiki-studio rename + CI contract
test (no code change). 0.5.0 = the extra, lint feedback and promote gate in
`wiki_export`, the benchmark adapter, the lifecycle suite and the report.

## Technical Context

**Language/Version**: Python 3.11–3.13, Poetry, pydantic 2, FastMCP (`mcp` 1.x), ChromaDB 1.5; wiki-studio ≥ 0.2 (stdlib-only) as an optional extra
**Primary Dependencies**: `src/memkernel/wiki/{sync,pages,studio}.py`, `src/memkernel/mcp/tools/wiki.py`, `src/memkernel/config.py`, `pyproject.toml`, `docs/adr/ADR-010-*.md`, `eval/agent-memory-bench/**` (adapter mirror, preregistration, results, report), `eval/lifecycle-suite/**` (tasks, oracles, diagnostics, secret scan), `eval/check_freeze.py`, `tests/unit/test_wiki.py`, `tests/unit/test_wiki_studio.py`, `tests/unit/test_{lifecycle_suite,benchmark_diagnostics,check_freeze}.py`, `.github/workflows/ci.yml` (one added step, see FR-004)
**Testing**: fast suite as in 0.4; wiki-studio contract tests run only when `wiki_studio` imports (skip otherwise, never fail-silent in CI: CI installs the extra); lifecycle tasks' reference solutions asserted in CI with no model call; diagnostics, secret scan and freeze verifier tested on fixtures
**Constraints**: no new *required* runtime dependency; the extra is the first optional dependency and gets ADR-010; silent when absent; MCP tool count stays nine; no subprocess to a copilot CLI from inside the server; no benchmark runner, judge or statistics of our own; the run is never a CI gate; no claim about token savings beyond what the harness's cost ledger shows

## Constitution Check

| Rule file | Concern | Status |
|-----------|---------|--------|
| `coding-standards.md` | No magic strings; thresholds in config, not code | OK — thresholds live in `preregistration.md`; the adapter's mapping lives in `config.frozen.json` |
| `safety.md` | Sandbox isolation, data handling of live runs | OK — the harness owns the sandbox and admission gate; results follow its `DATA_SAFETY.md`; a secret scan gates every commit of results |
| `copilot-conventions.md` | Scope proportional to the claim; reuse before build | OK — no query/ingest adoption; the public harness is reused, only an adapter and tasks are built; run labelled descriptive below the predeclared sample |
| project `CLAUDE.md` | New dependency needs an ADR; tool count < 10 | OK — ADR-010; `wiki_export` grows a report, no tool added |

## Cross-repository sequence

| # | Repo | Deliverable | Depends on | Unblocks |
|---|------|-------------|------------|----------|
| 1 | memkernel | 0.4.1: positioning docs, `ai-wiki` → wiki-studio, CI contract test (US1) | — | first benchmark run (frozen integration) |
| 2 | wiki-studio | 0.2.0: `api.propose(...)` + documented patch-set format, `wiki_studio.schema` module (page types → dir, required sections), `consumers.md` recipe fix | — | US2 |
| 3 | memkernel | 0.5.0 US2: `[wiki]` extra, ADR-010, lint feedback and promote gate in `wiki_export`, schema contract test | 1, 2 | S4 scenario of the benchmark |
| 4 | memkernel | 0.5.0 US3: adapter + frozen config, lifecycle suite, diagnostics, freeze verifier; upstream PRs to the benchmark | 1 (docs only); benchmark commit pinned | US4 |
| 5 | memkernel | 0.5.0 US4: preregistration, run, report, release | 3, 4 | README evidence link |

The #17 contributor's protocol text, if it arrives, is folded into the
preregistration; the adapter, suite and run stay with the maintainers.

## Phase plan

- **US1** (0.4.1) — docs only; mergeable now; tag `v0.4.1`.
- **US2** (0.5.0) — tasks 5–8 work against wiki-studio 0.1.0 (extra,
  ADR-010, lint adapter); tasks 9–10 (promote gate, schema contract test)
  need 0.2.0 and move to 0.5.1 if it slips.
- **US3** (0.5.0) — independent of US2; starts immediately.
- **US4** (0.5.0) — after US2 and US3; the only phase that spends money.
  Sequence: merge US2 and US3, set the version to `0.5.0rc1`, record that
  SHA, commit the preregistration, run, commit the harness's published
  results and the report, bump to `0.5.0`, verify with `check_freeze.py`,
  tag.

## Risks

- wiki-studio 0.2.0 timing: mitigated by the US2 fallback above.
- Harness maturity: the benchmark has no release, about thirty commits, one
  public run on a non-Claude model with a null headline, and is written by
  the authors of a competing product (disclosed). Mitigations: pin by commit;
  fill the vendor-review template; keep the mirror in this repo so the run
  is reproducible if upstream moves; report the benchmark's own caveats.
- Harness fit for the lifecycle suite: the harness feeds a corpus before the
  grid and does not run multi-session writes by default. Task 11 establishes
  on the dry run whether `harness.lifecycle` carries each arm's
  first-session state into the next session (`lc-retain`) and whether the
  executor supports a compaction-length session with the arm's
  `PreCompact`/`PostCompact` hooks (`lc-compact`, within-session); a missing
  capability is contributed upstream first and its group is left out of
  0.5.0, saying so. `lc-reval` and `lc-wiki` always ship.
- Oracle leakage: the memkernel arm ingests verbatim transcript bytes only
  (FR-012); any labelled fact or supersession metadata in the store would
  make the comparison invalid, and the vendor review states this.
- Run cost: not estimated here. The grid is up to 26 tasks × 5 conditions
  × 6 arms = 780 cells before `xs-*` and the lifecycle suite, and the
  harness's admission pairing decides what is actually run. Task 11 records
  the exact resolved cell count from the pinned harness's dry run and the
  budget at explicit prices; the preregistration carries both; the run is
  descriptive if below the predeclared sample.
- Data: only the harness's published outputs are committed; a secret scan
  gates the commit (FR-017).

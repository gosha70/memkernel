# Tasks: memkernel 0.5 — evidence and wiki-studio

<!-- One `## US<n>:` group = one auto-build phase. [US#] tags trace to spec.md. -->
<!-- Run per phase: poetry run ruff check src/ tests/ templates/ eval/ && poetry run ruff format --check src/ tests/ templates/ eval/ && poetry run mypy src/ && poetry run pytest -m "not slow" -q -p no:cacheprovider -->
<!-- Track B harness: GiulioDER/agent-memory-bench at eval/agent-memory-bench/BENCHMARK_COMMIT; nothing of it is vendored. -->

## US1: Positioning and the wiki-studio contract (release 0.4.1)

| # | [P] | Task | File(s) | Owner | Done |
|---|-----|------|---------|-------|------|
| 1 | | Done in PR #18 (94016f5) before approval: README positioning section and roadmap evidence item; nothing to build, do not re-add (FR-001) | `README.md`, `docs/roadmap.md` | — | [x] |
| 2 | [P] | `ai-wiki` → wiki-studio in README (bridge section, Related projects), roadmap ("lint and health via wiki-studio"), dated note in ADR-008 (FR-002) | `README.md`, `docs/roadmap.md`, `docs/adr/ADR-008-llm-wiki-as-semantic-layer.md` | build | [ ] |
| 3 | | wiki-studio as a dev dependency; exporter → `wiki_studio.api.lint` contract test, skipped without the import (FR-003, FR-004) | `pyproject.toml`, `poetry.lock`, `tests/unit/test_wiki.py` | build | [ ] |
| 4 | | Version 0.4.1, CHANGELOG `[0.4.1]` (docs and contract test only) (FR-019) | `pyproject.toml`, `src/memkernel/__init__.py`, `CHANGELOG.md` | build | [ ] |

**Checkpoint US1** — verify before continuing:
- [ ] Contract test runs in CI (dev group installed) and passes against wiki-studio 0.1.0
- [ ] `ci.yml` untouched, or the single FR-004 condition documented in the PR
- [ ] Tag `v0.4.1` after merge (driver)

---

## US2: wiki-studio is the wiki maintainer (release 0.5.0; tasks 5–8 on wiki-studio 0.1, tasks 9–10 need 0.2.0)

| # | [P] | Task | File(s) | Owner | Done |
|---|-----|------|---------|-------|------|
| 5 | [P] | Open the wiki-studio issue for FR-010 (`api.propose`, `wiki_studio.schema`, `consumers.md` fix) with the contract memkernel needs | wiki-studio issue | driver | [ ] |
| 6 | [P] | ADR-010: wiki-studio as wiki maintainer, optional extra, adopted and rejected capabilities, fallback (FR-005) | `docs/adr/ADR-010-wiki-studio-as-wiki-maintainer.md` | build | [ ] |
| 7 | | `[wiki]` extra `wiki-studio>=0.1,<1`; README install lines; lazy import helper, silent when absent, warning only on explicit request (FR-005, FR-006) | `pyproject.toml`, `README.md`, `src/memkernel/wiki/studio.py` | build | [ ] |
| 8 | | Post-export lint adapter against wiki-studio 0.1: `ExportReport.lint: LintSummary | None` with `HealthItem` copied field for field from `HealthFinding`; `wiki_export` returns `"lint"` or `null` + `lint_hint`; tool set stays nine; tests with the extra and with the import simulated absent; pyproject optional-extra test (FR-006, FR-008, SC-1) | `src/memkernel/wiki/studio.py`, `src/memkernel/wiki/sync.py`, `src/memkernel/mcp/tools/wiki.py`, `tests/unit/test_wiki_studio.py` | build | [ ] |
| 9 | | **(≥ 0.2)** Raise the pin to `>=0.2,<1`; `wiki_proposals_dir` setting + README row; `WikiExporter.export()` through `propose` + `promote`, direct writer otherwise; gate tests: clean export identical to direct write, violating draft rejected, 0.1 or no extra → unchanged (FR-007) | `pyproject.toml`, `src/memkernel/config.py`, `src/memkernel/wiki/sync.py`, `README.md`, `tests/unit/test_wiki_studio.py` | build | [ ] |
| 10 | | **(≥ 0.2)** Raise the dev pin to `>=0.2,<1` and update `poetry.lock`; schema contract test (`EXPORT_MAP`, `IMPORT_MAP`, `PAGE_SECTIONS` vs `wiki_studio.schema`) that fails on a missing module unless `MK_TEST_NO_EXTRA=1` (FR-009, FR-019) | `pyproject.toml`, `poetry.lock`, `tests/unit/test_wiki.py` | build | [ ] |

**Checkpoint US2** — verify before continuing:
- [ ] `poetry run pytest tests/unit/test_wiki.py tests/unit/test_wiki_studio.py tests/e2e -q` green with the schema test running (not skipped); the simulated-absent tests pass; exactly nine tools
- [ ] Fallback if wiki-studio 0.2.0 is not out: ship tasks 5–8 (extra at `>=0.1`, lint adapter, no gate, no schema test); tasks 9–10 move to 0.5.1 and the README says the gate is not yet active

---

## US3: memkernel as an arm of agent-memory-bench

| # | [P] | Task | File(s) | Owner | Done |
|---|-----|------|---------|-------|------|
| 11 | | Pin the benchmark commit; run its dry run from a clean checkout; record in `NOTES.md`: the adapter contract (`harness.adapters.base.MemoryAdapter`, admission signals), for each lifecycle group its required mechanism and whether the pinned harness (`harness.lifecycle`, `harness.sequence*`, the executor) provides it: cross-session carry-over (`lc-retain`), carry-over plus repository mutation between sessions (`lc-reval`), workspace filesystem carried into a second namespace's session (`lc-wiki`), compaction-length session with `PreCompact`/`PostCompact` hooks (`lc-compact`), and the **exact resolved cell count** for the planned arms and task set with the derived budget at explicit prices (FR-011, FR-014, FR-015) | `eval/agent-memory-bench/BENCHMARK_COMMIT`, `eval/agent-memory-bench/NOTES.md` | build | [ ] |
| 12 | | Adapter module: install from the pinned wheel, write the arm's `.claude/settings.json` from `templates/` (server, hooks, CLAUDE.md block), namespace → `MEMKERNEL_PROJECT_ID`, admission signals, teardown; nothing reaches memkernel internals (FR-011) | `eval/agent-memory-bench/adapter.py` | build | [ ] |
| 13 | | Ingest path over MCP: verbatim transcripts as `document` records and nothing else; mapping and the document-store mode (`document_store: local`, chunking, summary and embedding settings) recorded in `config.frozen.json`; `versions.lock`; `instruction_appendix.md` with published size; vendor-review template filled (FR-011, FR-012) | `eval/agent-memory-bench/{config.frozen.json,versions.lock,instruction_appendix.md,VENDOR_REVIEW.md}` | build | [ ] |
| 14 | | Lifecycle suite tasks in the benchmark format for every group whose mechanism task 11 confirmed (`lc-retain` incl. revised-fact variants, `lc-reval`, `lc-wiki`, `lc-compact`); an upstream harness-extension PR first for each missing mechanism; same-first-session exposure for every arm; naive and informed references and oracles; CI test asserting fail/pass with no model call (FR-015) | `eval/lifecycle-suite/tasks/**`, `eval/lifecycle-suite/oracles/**`, `tests/unit/test_lifecycle_suite.py` | build | [ ] |
| 15 | [P] | `diagnostics.py` over harness streams (re-reads after resume, tokens and wall time, calls before first `retain`, recall-to-use) + fixture stream test; `scan_secrets.py` + planted-secret fixture test (FR-016, FR-017) | `eval/lifecycle-suite/diagnostics.py`, `eval/lifecycle-suite/scan_secrets.py`, `eval/lifecycle-suite/fixtures/**`, `tests/unit/test_benchmark_diagnostics.py` | build | [ ] |
| 16 | [P] | `check_freeze.py <code-freeze-sha>`: reads `PREREG_COMMIT`; allowlist, version-line-only diff check; preregistration lock (named commit is a descendant of the code-freeze SHA and an ancestor of HEAD, diffs by exactly `preregistration.md`, equals the first entry of `rev-list --reverse --ancestry-path` for that file, blob equal at HEAD); unit test on a synthetic repo incl. a case that moves `PREREG_COMMIT` to a later commit and a case where no commit touches `eval/agent-memory-bench/preregistration.md` after the freeze, both asserted rejected (FR-018) | `eval/check_freeze.py`, `tests/unit/test_check_freeze.py` | build | [ ] |
| 17 | | Upstream pull requests: `adapters/memkernel/` and the lifecycle tasks against the pinned benchmark commit; link both from `NOTES.md` (FR-011, FR-015) | benchmark repo PRs | driver | [ ] |

**Checkpoint US3** — verify before continuing:
- [ ] `python -m scripts.pilot --dry-run --arms bare,claude_md,fs_grep,memkernel` succeeds in the pinned benchmark checkout with the mirror copied in (SC-4)
- [ ] `poetry run pytest tests/unit/test_lifecycle_suite.py tests/unit/test_benchmark_diagnostics.py tests/unit/test_check_freeze.py -q` green; `ruff check eval/` clean
- [ ] If the #17 contributor's PR arrived, its protocol text is folded into `preregistration.md` rather than kept as a parallel document

---

## US4: Preregistered run and release 0.5.0

| # | [P] | Task | File(s) | Owner | Done |
|---|-----|------|---------|-------|------|
| 18 | | Code freeze: `main` after US2 + US3 with version `0.5.0rc1`, record the SHA; then the preregistration commit adding only `preregistration.md` (benchmark commit, code-freeze SHA, Claude model, arms, task set, seeds, the resolved cell count and budget from task 11, prices, endpoint, threshold, no-gain band, minimum sample) and `PREREG_COMMIT`; push the preregistration commit and post its SHA and the file's sha256 on issue #17 before any session (FR-014, FR-018) | `eval/agent-memory-bench/preregistration.md` | driver | [ ] |
| 19 | | Run the official grid + `xs-*` + lifecycle suite on arms `bare`, `claude_md`, `placebo`, `protocol`, `fs_grep`, `memkernel`; commit only the harness's published results after `scan_secrets.py` passes (FR-013, FR-017) | `eval/agent-memory-bench/results/<run_id>/**` | driver | [ ] |
| 20 | | `report-0.5.0.md` from the harness statistics + `diagnostics.py`; nulls and discarded cells included; descriptive-or-inferential label; names benchmark commit, code-freeze SHA, preregistration commit, tag (FR-018) | `eval/agent-memory-bench/report-0.5.0.md` | driver | [ ] |
| 21 | | README evidence line links the report; CHANGELOG `[0.5.0]`; version 0.5.0; `check_freeze.py <code-freeze-sha>` passes (FR-018, FR-019) | `README.md`, `CHANGELOG.md`, `pyproject.toml`, `src/memkernel/__init__.py` | build | [ ] |
| 22 | | **After the `v0.5.0` tag**: roadmap ticks in a post-release commit; reply on #17 with the report link and the gaps the run exposed (FR-018) | `docs/roadmap.md`, issue #17 | driver | [ ] |

**Checkpoint US4**:
- [ ] `python eval/check_freeze.py <code-freeze-sha>` exits 0 on the release commit (SC-8)
- [ ] The issue #17 comment naming the preregistration commit and sha256 is timestamped before the first session in `results/`, and its sha256 equals that commit's blob (SC-5)
- [ ] Full gate green; nine tools; coverage ≥ 80 percent
- [ ] Tag `v0.5.0` after merge (driver); task 22 only after the tag

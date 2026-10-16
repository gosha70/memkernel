# Tasks: memkernel 0.5 — evidence and wiki-studio

<!-- One `## US<n>:` group = one auto-build phase. [US#] tags trace to spec.md. -->
<!-- Run per phase: poetry run ruff check src/ tests/ templates/ eval/ && poetry run ruff format --check src/ tests/ templates/ eval/ && poetry run mypy src/ && poetry run pytest -m "not slow" -q -p no:cacheprovider -->
<!-- Track B amended 2026-10-16 (option B): lifecycle runner of our own, four groups only; upstream retrieval arm is US5, not a release gate. -->

## US1: Positioning and the wiki-studio contract (release 0.4.1)

| # | [P] | Task | File(s) | Owner | Done |
|---|-----|------|---------|-------|------|
| 1 | | Done in PR #18 (94016f5) before approval: README positioning section and roadmap evidence item; nothing to build, do not re-add (FR-001) | `README.md`, `docs/roadmap.md` | — | [x] |
| 2 | [P] | `ai-wiki` → wiki-studio in README (bridge section, Related projects), roadmap ("lint and health via wiki-studio"), dated note in ADR-008 (FR-002) | `README.md`, `docs/roadmap.md`, `docs/adr/ADR-008-llm-wiki-as-semantic-layer.md` | build | [x] |
| 3 | | wiki-studio as a dev dependency; exporter → `wiki_studio.api.lint` contract test, skipped without the import (FR-003, FR-004) | `pyproject.toml`, `poetry.lock`, `tests/unit/test_wiki.py` | build | [x] |
| 4 | | Version 0.4.1, CHANGELOG `[0.4.1]` (docs and contract test only) (FR-019) | `pyproject.toml`, `src/memkernel/__init__.py`, `CHANGELOG.md` | build | [x] |

**Checkpoint US1** — verify before continuing:
- [x] Contract test runs in CI (dev group installed) and passes against wiki-studio 0.1.0
- [x] `ci.yml` untouched, or the single FR-004 condition documented in the PR
- [x] Tag `v0.4.1` after merge (driver): v0.4.1 on 24f354d, PyPI lists 0.4.1 (wheel + sdist)

---

## US2: wiki-studio is the wiki maintainer (release 0.5.0; tasks 5–8 on wiki-studio 0.1, tasks 9–10 need 0.2.0)

| # | [P] | Task | File(s) | Owner | Done |
|---|-----|------|---------|-------|------|
| 5 | [P] | Open the wiki-studio issue for FR-010 (`api.propose`, `wiki_studio.schema`, `consumers.md` fix) with the contract memkernel needs | wiki-studio issue | driver | [x] |
| 6 | [P] | ADR-010: wiki-studio as wiki maintainer, optional extra, adopted and rejected capabilities, fallback (FR-005) | `docs/adr/ADR-010-wiki-studio-as-wiki-maintainer.md` | build | [x] |
| 7 | | `[wiki]` extra `wiki-studio>=0.1,<1`; README install lines; lazy import helper, silent when absent, warning only on explicit request (FR-005, FR-006) | `pyproject.toml`, `README.md`, `src/memkernel/wiki/studio.py` | build | [x] |
| 8 | | Post-export lint adapter against wiki-studio 0.1: `ExportReport.lint: LintSummary | None` with `HealthItem` copied field for field from `HealthFinding`; `wiki_export` returns `"lint"` or `null` + `lint_hint`; tool set stays nine; tests with the extra and with the import simulated absent; pyproject optional-extra test (FR-006, FR-008, SC-1) | `src/memkernel/wiki/studio.py`, `src/memkernel/wiki/sync.py`, `src/memkernel/mcp/tools/wiki.py`, `tests/unit/test_wiki_studio.py` | build | [x] |
| 9 | | **(≥ 0.2)** Raise the pin to `>=0.2,<1`; `wiki_proposals_dir` setting + README row; `WikiExporter.export()` through `propose` + `promote`, direct writer otherwise; gate tests: clean export identical to direct write, violating draft rejected, 0.1 or no extra → unchanged (FR-007) | `pyproject.toml`, `src/memkernel/config.py`, `src/memkernel/wiki/sync.py`, `README.md`, `tests/unit/test_wiki_studio.py` | build | [ ] |
| 10 | | **(≥ 0.2)** Raise the dev pin to `>=0.2,<1` and update `poetry.lock`; schema contract test (`EXPORT_MAP`, `IMPORT_MAP`, `PAGE_SECTIONS` vs `wiki_studio.schema`) that fails on a missing module unless `MK_TEST_NO_EXTRA=1` (FR-009, FR-019) | `pyproject.toml`, `poetry.lock`, `tests/unit/test_wiki.py` | build | [ ] |

**Checkpoint US2** — verify before continuing:
- [ ] `poetry run pytest tests/unit/test_wiki.py tests/unit/test_wiki_studio.py tests/e2e -q` green with the schema test running (not skipped); the simulated-absent tests pass; exactly nine tools
- [ ] Fallback if wiki-studio 0.2.0 is not out: ship tasks 5–8 (extra at `>=0.1`, lint adapter, no gate, no schema test); tasks 9–10 move to 0.5.1 and the README says the gate is not yet active

---

## US3: Lifecycle runner, tasks and checks

| # | [P] | Task | File(s) | Owner | Done |
|---|-----|------|---------|-------|------|
| 11 | | Task 11 investigation of `agent-memory-bench` at `c1b15726`: adapter contract, mechanism per lifecycle group, admission, cell count, data safety, model route (FR-011–FR-020 basis) | `specs/memkernel-0-5/research/2026-10-15-task11-agent-memory-bench.md` | build | [x] |
| 12 | | `runner.py`: run root, chains, fresh workspace / `HOME` / `CLAUDE_CONFIG_DIR` per session, persistence rule per arm, namespace switch, `claude -p --output-format stream-json`, checker invocation, raw streams outside the checkout (FR-011, FR-012) | `eval/lifecycle-suite/runner.py` | build | [ ] |
| 13 | [P] | Six arm configurations with frozen persistence rules, instruction bytes and allowed tools; persistence-rule unit test (FR-012, SC-8) | `eval/lifecycle-suite/arms/**`, `tests/unit/test_lifecycle_arms.py` | build | [ ] |
| 14 | [P] | Lifecycle tasks, four groups, five to eight each, benchmark task format, naive and informed references, oracles; CI test of references with no model call (FR-013) | `eval/lifecycle-suite/tasks/**`, `eval/lifecycle-suite/oracles/**`, `tests/unit/test_lifecycle_suite.py` | build | [ ] |
| 15 | | `runner.py --demo`: stub agent, scripted sessions, simulated compaction and hook events; CI test (FR-014, SC-4) | `eval/lifecycle-suite/runner.py`, `tests/unit/test_lifecycle_demo.py` | build | [ ] |
| 16 | [P] | Receipts and diagnostics (counts only), `scan_secrets.py` with planted-secret fixture, report step deriving `report-<version>.md` from records (FR-017, FR-018) | `eval/lifecycle-suite/{records,diagnostics,scan_secrets,report}.py`, `eval/lifecycle-suite/fixtures/**`, `tests/unit/test_lifecycle_records.py` | build | [ ] |
| 17 | [P] | `check_freeze.py <code-freeze-sha>` reading `PREREG_COMMIT`: allowlist, version-line-only diff, preregistration lock; synthetic-repo test incl. a moved `PREREG_COMMIT` and no commit touching the file, both rejected (FR-017) | `eval/check_freeze.py`, `tests/unit/test_check_freeze.py` | build | [ ] |

**Checkpoint US3** — verify before continuing:
- [ ] `poetry run pytest tests/unit/test_lifecycle_*.py tests/unit/test_check_freeze.py -q` green on Python 3.11; `ruff check eval/` clean
- [ ] `python eval/lifecycle-suite/runner.py --demo` passes with no credentials (SC-4)
- [ ] The runner contains no retrieval-grid code and no statistics beyond FR-017's counts and paired differences (FR-011)

---

## US4: Calibration, preregistered run and release 0.5.0

| # | [P] | Task | File(s) | Owner | Done |
|---|-----|------|---------|-------|------|
| 18 | | Calibration on the chosen Claude model: live compaction with `PreCompact`/`PostCompact` recorded (or `lc-compact` dropped), per-arm token usage by class, wiring failures; record configuration, cost, exclusions; freeze tasks and arm configurations (FR-015) | `eval/lifecycle-suite/calibration/**` | driver | [ ] |
| 19 | | Code freeze: `main` after US2 + US3 with version `0.5.0rc1`; preregistration commit adding only `preregistration.md` (budget from calibration at explicit prices); `PREREG_COMMIT`; push and post the SHA and sha256 on #17 before any measured session (FR-016, FR-017) | `eval/lifecycle-suite/preregistration.md`, `eval/lifecycle-suite/PREREG_COMMIT` | driver | [ ] |
| 20 | | Measured run, all arms and admitted groups; `scan_secrets.py` and operator review; commit receipts (FR-017, FR-018) | `eval/lifecycle-suite/results/<run_id>/**` | driver | [ ] |
| 21 | | `report-0.5.0.md` labelled maintainer-run supplemental evaluation; README evidence line; CHANGELOG `[0.5.0]`; version 0.5.0; `check_freeze.py` passes (FR-017, FR-019) | `eval/lifecycle-suite/report-0.5.0.md`, `README.md`, `CHANGELOG.md`, `pyproject.toml`, `src/memkernel/__init__.py` | build | [ ] |
| 22 | | **After the `v0.5.0` tag**: roadmap ticks in a post-release commit; reply on #17 with the report link and its limits (FR-017) | `docs/roadmap.md`, issue #17 | driver | [ ] |

**Checkpoint US4**:
- [ ] `python eval/check_freeze.py <code-freeze-sha>` exits 0 on the release commit (SC-8)
- [ ] The #17 comment naming the preregistration commit and sha256 is timestamped before the first measured session, and its sha256 equals that commit's blob (SC-5)
- [ ] Full gate green; nine tools; coverage ≥ 80 percent
- [ ] Tag `v0.5.0` after merge (driver); task 22 only after the tag

---

## US5: Upstream retrieval arm (not a release gate)

| # | [P] | Task | File(s) | Owner | Done |
|---|-----|------|---------|-------|------|
| 23 | | Post the integration questions to `agent-memory-bench` (owner's approval required) | upstream issue | driver | [ ] |
| 24 | | After upstream confirms the path: adapter per FR-020 (rendered transcripts, document-store mode declared, write tools withheld), upstream PR; report any results separately with the read-only-retrieval statement | `agent-memory-bench` PR | build | [ ] |

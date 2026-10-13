# Tasks: memkernel 0.4 — code revalidation, store health pass

<!-- One `## US<n>:` group = one auto-build phase. [US#] tags trace to spec.md. -->
<!-- Run per phase: poetry run ruff check src/ tests/ templates/ && poetry run ruff format --check src/ tests/ templates/ && poetry run mypy src/ && poetry run pytest -m "not slow" -q -p no:cacheprovider -->

## US1: Code memories have a source-bound identity and a changed file replaces the old snapshot

| # | [P] | Task | File(s) | Owner | Done |
|---|-----|------|---------|-------|------|
| 1 | [P] | Settings `project_root`, `health_duplicate_threshold`, `health_duplicate_limit`, `health_report_limit`; README configuration rows for every new `MEMKERNEL_*` setting (FR-001) | `src/memkernel/config.py`, `README.md` | build | [x] |
| 2 | [P] | `Memory.needs_review` / `review_reason` / `superseded_by` / `parent_ref`; constants (`CODE_CHUNK_TAG`, `CODE_CHUNK_KEY`, `PARENT_REF_KEY`, review reasons); adapter loads every new key with its default (FR-002) | `src/memkernel/core/models.py`, `src/memkernel/storage/chroma.py` | build | [x] |
| 3 | | `VectorStorePort.find_by_hash(content_hash, memory_type, source=None)` never returning a chunk record; `list_all(where=None, include_content=True)` with an ids-and-metadata-only path (FR-008, FR-009) | `src/memkernel/core/ports.py`, `src/memkernel/storage/chroma.py` | build | [x] |
| 4 | | Owner-specific code chunk records: ids `<canonical>-chunk-<n>`, `code_chunk` tag + boolean key, `parent_ref`, no dedup; `superseded_by` / `needs_review` propagate to owned chunks; `forget` deletes owned chunks and legacy `chunk_refs` targets only when unreferenced (FR-007) | `src/memkernel/core/services.py` | build | [x] |
| 5 | | Sourced code identity `(source, hash)`: canonical lookup before chunking so a dedup hit embeds nothing; auto-supersession sets `supersedes` on the new and `superseded_by` on every live old canonical (and their chunks), deletes their owned chunks, keeps them; explicit `supersedes` sets the marker (FR-008) | `src/memkernel/core/services.py` | build | [x] |
| 6 | | `_filter_live` drops `superseded_by` records and chunks with a dead `parent_ref` (window check kept as fallback); `list_memories(include_superseded=False)`, `consolidate` and `WikiExporter.export` derive superseded from `superseded_by` (FR-004) | `src/memkernel/core/services.py`, `src/memkernel/wiki/sync.py` | build | [x] |
| 7 | [P] | Unit tests (identity per path, single-chunk file cannot shadow its canonical, dedup hit embeds nothing, shared-by-content chunks, old-only phrase hidden, pre-0.4 multiple canonicals, legacy chunk_refs rule, list_memories / consolidate / WikiExporter honour the marker, adapter defaults for missing keys, `list_all(include_content=False)`) and the e2e code round trip (FR-014) | `tests/unit/test_code_supersession.py`, `tests/unit/test_chroma.py`, `tests/unit/test_wiki.py`, `tests/e2e/test_mcp_roundtrip.py` | build | [x] |

**Checkpoint US1** — verify before continuing:
- [x] `poetry run mypy src/` clean; `poetry run ruff check src/ tests/ templates/` clean
- [x] `poetry run pytest tests/unit/test_code_supersession.py tests/unit/test_chroma.py tests/unit/test_wiki.py tests/e2e -q` green with exactly nine tools listed
- [x] Existing 0.3 tests still pass unchanged

---

## US2: Stale `code` memories are detected and kept out of recall

| # | [P] | Task | File(s) | Owner | Done |
|---|-----|------|---------|-------|------|
| 8 | | `MemoryService.revalidate()`: resolve `source` inside the `project_root` boundary (symlinks, `..`), whole-file hash compare, flag/clear canonical and owned chunk records, report; writes nothing else (FR-001, FR-003) | `src/memkernel/core/services.py` | build | [ ] |
| 9 | | `recall(include_needs_review=False)` exclusion applied in Python in `_filter_live` incl. chunk hits whose owner is flagged; `recall` MCP flag; test that a record without the key is still recalled (FR-004) | `src/memkernel/core/services.py`, `src/memkernel/mcp/tools/memory.py` | build | [ ] |
| 10 | | `consolidate(revalidate=False)` with `"revalidated"` report; MCP flag; `on_session_start` runs it and prints `### Needs review` only when non-empty (FR-005) | `src/memkernel/core/services.py`, `src/memkernel/mcp/tools/memory.py`, `src/memkernel/lifecycle.py` | build | [ ] |
| 11 | [P] | `POST /revalidate` admin endpoint (FR-006) | `src/memkernel/api/routes/admin.py` | build | [ ] |
| 12 | | Unit tests for revalidation (changed / missing / cleared / unknown / boundary escape / owned-chunk propagation), recall exclusion incl. missing-key record, consolidate report, lifecycle section, endpoint (FR-014) | `tests/unit/test_revalidation.py`, `tests/unit/test_lifecycle_component.py`, `tests/unit/test_admin_api.py` | build | [ ] |

**Checkpoint US2** — verify before continuing:
- [ ] `poetry run pytest tests/unit/test_revalidation.py tests/unit/test_lifecycle_component.py tests/unit/test_admin_api.py -q` green
- [ ] `poetry run pytest -m "not slow" -q` green; mypy and ruff clean

---

## US3: The store reports its own health

| # | [P] | Task | File(s) | Owner | Done |
|---|-----|------|---------|-------|------|
| 13 | | `HealthReport` / `HealthItem` models; `MemoryService.health(full=True)` with the seven categories (incl. `unmarked_supersessions`; stale sources: code only; orphans: document parts and tagged code chunks), bounded items, quick/full split using `list_all(include_content=False)`, near-duplicates over non-chunk candidates filtered on long-term type values with already-linked pairs excluded, complete within the candidate set (FR-009) | `src/memkernel/core/models.py`, `src/memkernel/core/services.py` | build | [ ] |
| 14 | [P] | `GET /health/store`; `/health` unchanged (FR-010) | `src/memkernel/api/routes/admin.py` | build | [ ] |
| 15 | [P] | `"health"` summary in `memory://status` and in the `consolidate()` report; `### Store health` line at session start (FR-011, FR-012) | `src/memkernel/mcp/server.py`, `src/memkernel/core/services.py`, `src/memkernel/lifecycle.py` | build | [ ] |
| 16 | | Unit tests: one seeded defect per category incl. an unmarked legacy supersession and a pre-0.2 record without a tier label found as a neighbour, quick vs full, chunk/part exclusion and linked-pair exclusion from near-duplicates, endpoint, resource, consolidate summary, lifecycle line (FR-014) | `tests/unit/test_health.py`, `tests/unit/test_admin_api.py`, `tests/unit/test_lifecycle_component.py`, `tests/e2e/test_mcp_roundtrip.py` | build | [ ] |

**Checkpoint US3** — verify before continuing:
- [ ] `poetry run pytest -m "not slow" -q` green; mypy and ruff clean
- [ ] `health(full=False)` on a 500-memory store completes without embedding calls and without loading content (assert on a counting MockEmbedding and a recording store); `health()` finds all three pairs among three near-identical memories

---

## US4: Release hygiene

| # | [P] | Task | File(s) | Owner | Done |
|---|-----|------|---------|-------|------|
| 17 | | Bump to `0.4.0`; `[0.4.0]` CHANGELOG section incl. the `Changed` line for auto-supersession on `retain(type="code")` and sourced-code identity; ADR-007 supersession note (FR-013, FR-015) | `pyproject.toml`, `src/memkernel/__init__.py`, `CHANGELOG.md`, `docs/adr/ADR-007-tiered-memory.md` | build | [ ] |
| 18 | [P] | README: revalidation, auto-supersession, health pass, settings, flags, endpoints, when to set `MEMKERNEL_PROJECT_ROOT`; CLAUDE.md template: `needs_review` guidance; hook templates and `templates/kiro/settings/mcp.json` set `MEMKERNEL_PROJECT_ROOT` (FR-013) | `README.md`, `templates/claude-memory-instructions.md`, `templates/hooks/*.py`, `templates/kiro/settings/mcp.json` | build | [ ] |
| 19 | [P] | Roadmap: tick revalidation and health, relabel ecosystem 0.5; memory-tiers.md rows for revalidation and health (FR-013) | `docs/roadmap.md`, `docs/architecture/memory-tiers.md` | build | [ ] |

**Checkpoint US4** — verify before continuing:
- [ ] `poetry build` succeeds and the wheel installs in a clean venv
- [ ] Coverage ≥ 80 percent: `poetry run pytest -m "not slow" --cov=memkernel --cov-fail-under=80 -q`

---

## Final Verification

- [ ] Type checker: 0 errors
- [ ] Linter: 0 errors
- [ ] All existing tests pass
- [ ] No [NEEDS CLARIFICATION] markers remain in spec.md
- [ ] Registered MCP tools are exactly: retain, recall, get, forget, promote, consolidate, ask, wiki_export, wiki_import
- [ ] `.github/workflows/ci.yml` unchanged; no dependency added; `docs/adr/` untouched except the ADR-007 note

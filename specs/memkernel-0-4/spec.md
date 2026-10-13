---
spec_mode: full
feature_id: memkernel-0-4
risk_category: feature
status: draft
date: 2026-10-12
---

# Spec: memkernel 0.4 — code revalidation, store health pass

<!-- Project constitution: shared/skills/ — copilot-conventions, coding-standards, safety -->

Design references (read before building): `docs/architecture/memory-tiers.md`,
`docs/adr/ADR-007-tiered-memory.md` (supersession model), `docs/adr/ADR-009-rlm-studio-for-documents.md`
(document parts, `document_part` marker), issues #9 and #10, `specs/memkernel-0-4/origin/2026-10-12-decisions.md`.

## User Scenarios

### US1: Stale `code` memories are detected and kept out of recall (Priority: HIGH)

**Given** a `code` memory retained from `src/app.py` and a later edit or deletion of that file
**When** the session starts (hook or `MemoryLifecycle.on_session_start()`), or `consolidate(revalidate=True)` runs, or the harness calls `revalidate()`
**Then** the memory (and its chunk records) is marked `needs_review` with the reason `changed` or `missing`, default `recall` no longer returns it, `get` still does and shows the flag, and the session-start text lists what needs review

### US2: Re-retaining a changed file replaces the old snapshot (Priority: HIGH)

**Given** a live `code` memory for `src/app.py`
**When** the agent calls `retain(content=<new file>, type="code", source="src/app.py")`
**Then** the new memory supersedes the old one, the old chunk records are removed, recall returns only the new snapshot, and the old canonical record survives as a superseded record for provenance; identical content still dedups to the existing ref_id

### US3: The store reports its own health (Priority: HIGH)

**Given** a store that has accumulated orphans, dangling links, missing sources, near-duplicates and expired-but-present records
**When** a curator calls `MemoryService.health()` or `GET /health/store`, or an agent reads `memory://status` or a `consolidate()` report
**Then** they get a read-only report with counts per category and up to a bounded number of items each, with the expensive near-duplicate pass only in the full report

### US4: Release hygiene (Priority: LOW)

**Given** the 0.4 changes are complete
**When** the release is prepared
**Then** the version is `0.4.0`, the CHANGELOG lists the changes, the README documents revalidation, the health pass, the new settings and the new flags, the roadmap reflects what shipped, and the MCP tool count is unchanged at nine

## Requirements

- **FR-001**: Settings MUST gain `project_root: str = "."` (`MEMKERNEL_PROJECT_ROOT`), `health_duplicate_threshold: float = 0.95` (`MEMKERNEL_HEALTH_DUPLICATE_THRESHOLD`, cosine similarity in [0, 1]), `health_duplicate_limit: int = 500` (`MEMKERNEL_HEALTH_DUPLICATE_LIMIT`) and `health_report_limit: int = 20` (`MEMKERNEL_HEALTH_REPORT_LIMIT`); every new `MEMKERNEL_*` setting MUST have a row in the README configuration table. **Filesystem boundary**: a `source` is joined to `project_root` (an absolute `source` is taken as given), then resolved with symlinks followed and `..` normalised; the resolved path MUST lie under the resolved `project_root`, otherwise it is outside the boundary: it is never read, and revalidation counts it as `unknown`. The same resolution is used wherever a `source` is read.
- **FR-002**: `Memory` MUST gain `needs_review: bool = False`, `review_reason: str = ""`, `superseded_by: str | None = None` and `parent_ref: str | None = None`, stored as metadata keys of the same names; every new metadata key (`needs_review`, `review_reason`, `superseded_by`, `parent_ref`, `code_chunk`) MUST load with its default in `storage/chroma.py` when absent, so records written by 0.1–0.3 keep working. `ArtifactRef` is unchanged.
- **FR-003**: `MemoryService.revalidate() -> dict` MUST, for every live canonical `code` memory with a non-empty `source`: resolve the path (FR-001); if the file is missing, set `needs_review=True, review_reason="missing"`; if the content hash of the **whole source file** (the same `compute_content_hash` used at retain time, over the file decoded as UTF-8; 0.4 hashes whole files only, never chunk ranges) differs from `content_hash`, set `needs_review=True, review_reason="changed"`; if it matches and the memory was flagged, clear the flag; apply the same flags to the memory's **owned** chunk records (FR-007: `parent_ref` equal to the canonical); legacy shared chunks are never flagged. A path outside the boundary or unreadable counts as `unknown` and is left untouched. The pass MUST NOT write anything else (no supersession backfill; see FR-009 `unmarked_supersessions`). The report is `{"checked", "changed", "missing", "cleared", "unknown", "flagged": [{"ref_id", "source", "reason"}]}`. No LLM, no git, no subprocess: plain file reads.
- **FR-004**: `recall` MUST exclude `needs_review` memories unless `include_needs_review=True`; the exclusion is applied in Python inside `_filter_live` (never as a store `where` clause), and a test MUST prove that a record without the `needs_review` key is still recalled. The `recall` MCP tool gains `include_needs_review: bool = False`. `_filter_live` MUST also drop every record whose `superseded_by` is set (durable liveness, independent of the result window; the existing result-window check stays as a fallback for unmarked legacy links), drop a chunk record whose `parent_ref` points at a missing record, and drop chunk hits whose owner is flagged or superseded. `WikiExporter.export`, `list_memories` and `consolidate` MUST derive "superseded" from `superseded_by` on each record, not from `supersedes` links on the fetched set; `list_memories` gains `include_superseded: bool = False`. `get` and `promote` are unaffected.
- **FR-005**: `consolidate(revalidate: bool = False)` MUST run `revalidate()` first when the flag is set and include its report under `"revalidated"`; the `consolidate` MCP tool exposes `revalidate`. `MemoryLifecycle.on_session_start()` MUST call `consolidate(limit=5, revalidate=True)` and append a `### Needs review` section listing `source — reason — ref_id` per flagged memory, only when the list is non-empty, keeping every existing heading unchanged.
- **FR-006**: The admin API MUST expose `POST /revalidate` returning the FR-003 report.
- **FR-007**: Chunk records of a `code` memory MUST be owner-specific: id `<canonical ref_id>-chunk-<n>`, tag `code_chunk` plus boolean metadata `code_chunk: true` (constants in `core/models.py`), `parent_ref=<canonical ref_id>`, written **without** content-hash dedup, so two files, or two versions of one file, that share a function keep separate chunk records and `chunk_refs` lists only owned chunks. `superseded_by` and `needs_review` set on a canonical MUST propagate to its owned chunks. `forget` of a canonical deletes its owned chunks; a legacy (untagged, shared) `chunk_refs` target is deleted only when no other record's `chunk_refs` references it. Legacy chunks are otherwise left alone: once their canonical is gone they are indistinguishable from ordinary `code` records, and the spec accepts that limitation rather than migrating them.
- **FR-008**: Sourced `code` identity MUST be `(source, content_hash)`: `VectorStorePort.find_by_hash` gains an optional `source` filter (ChromaDB: one more `$and` clause) and MUST never return a code-chunk record (the adapter skips matches carrying `code_chunk: true`), so a single-chunk file cannot shadow its canonical. `retain(type=code)` with a non-empty `source` MUST look up the canonical first: a dedup hit (same source, same hash) returns the existing ref_id without chunking or embedding anything (counting-embedding test); identical content under another path is its own record. When the content differs from the live canonical `code` memory (or memories, in a pre-0.4 store) for `X`, the new canonical MUST get `supersedes=<newest old ref_id>`, every live canonical for `X` MUST get `superseded_by=<new ref_id>` (propagated to their owned chunks), the old canonicals' owned chunk records MUST be deleted from both indexes, and the old canonicals MUST remain as superseded records. An explicit `retain(..., supersedes=<ref>)` of any type MUST also set `superseded_by` on the target. Memories whose `source` is empty are never auto-superseded.
- **FR-009**: `MemoryService.health(full: bool = True) -> HealthReport` MUST be read-only and report, as `HealthItem(ref_id, detail)` lists bounded by `health_report_limit` plus a total count per category: `orphans` (document body/chunk records with no owning summary; `code_chunk` records whose `parent_ref` is missing — untagged legacy chunks are not detectable and are out of scope), `dangling_links` (`supersedes`, `superseded_by`, `promoted_from` or `parent_ref` pointing at a missing record), `unmarked_supersessions` (records that another record's `supersedes` points at but that carry no `superseded_by`: 0.2/0.3 links awaiting the fix mode), `stale_sources` (`code` memories only, whose resolved `source` path does not exist; `document` sources are names, not paths, and are excluded), `needs_review` (flagged memories), `expired_present` (short-term/working memories `forget_expired` would delete), and, only when `full=True`, `near_duplicates`: the candidate set is the at most `health_duplicate_limit` most recent live long-term memories excluding chunk and part records; each candidate is re-embedded through `EmbeddingPort` and queried with `search_dense(top_k=health_duplicate_limit, where tier=long_term)`; neighbours outside the candidate set and pairs already linked by `supersedes`, `superseded_by` or `promoted_from` are ignored; pairs with cosine similarity ≥ `health_duplicate_threshold` (similarity in [0, 1], default 0.95) are reported once (sorted ref pair); the result is complete within the candidate set. `HealthReport` and `HealthItem` are pydantic models in `core/models.py`; `HealthReport.summary` is `{category: count}`.
- **FR-010**: The admin API MUST expose `GET /health/store` (full report) and keep `GET /health` unchanged.
- **FR-011**: The `memory://status` resource and the `consolidate()` report MUST include `"health": <HealthReport.summary>` from `health(full=False)`.
- **FR-012**: `MemoryLifecycle.on_session_start()` MUST append a `### Store health` line (`orphans N, dangling links N, stale sources N, needs review N, expired N`) only when any count is non-zero.
- **FR-013**: `pyproject.toml` and `memkernel.__version__` MUST be `0.4.0`; `CHANGELOG.md` MUST gain a `[0.4.0]` section whose `Changed` list names the behaviour change on `retain(type="code")` (a changed file now supersedes the previous snapshot for the same `source` instead of adding a second live record) and the new sourced-code identity; `docs/adr/ADR-007-tiered-memory.md` MUST gain a short note in its supersession section recording automatic supersession by `source` for `code` memories and the durable `superseded_by` marker (the only ADR edit in this release); `README.md` MUST document revalidation, auto-supersession, the health pass, the four settings, the `include_needs_review` and `revalidate` flags and the two admin endpoints; `docs/roadmap.md` MUST tick git-diff-driven invalidation (as file-hash revalidation) and the health lint item, and relabel the ecosystem section 0.5; `docs/architecture/memory-tiers.md` MUST gain rows for revalidation and the health pass; `templates/claude-memory-instructions.md` MUST tell the agent what `needs_review` means and to re-retain the file.
- **FR-014**: Every new behaviour MUST have unit tests under `tests/unit/` (revalidation outcomes against `tmp_path` files, recall exclusion and the flag, consolidate and lifecycle sections, auto-supersession including identical content and legacy chunk detection, every health category, admin endpoints, status resource) and the e2e suite MUST cover `retain(code)` → edit file → `consolidate(revalidate=True)` → `recall` empty → `recall(include_needs_review=True)` → re-retain → `recall` returns only the new ref; coverage stays ≥ 80 percent; the registered MCP tools stay exactly the nine of 0.3.
- **FR-015**: No new runtime dependency; `.github/workflows/ci.yml` stays unchanged; no new ADR is required (no dependency decision); `docs/adr/` is not edited except for the ADR-007 supersession note named in FR-013.

## Constraints / What NOT to Build

- No warm/cold tiers, no `demote` / `archive`, no automatic `route` hints on `recall` (deliberate non-choices recorded when #3 was closed).
- No LLM in revalidation or health: no contradiction detection by model, no summarisation.
- No fix mode for health: the pass reports, it never mutates; the fix mode is a later feature once the report has run on real stores, and its first action is the `superseded_by` backfill for `unmarked_supersessions`.
- No new MCP tool: health and revalidation exist as `MemoryService` methods, admin endpoints and a `MemoryLifecycle` step; the only MCP exposure is the two optional flags on existing tools (`recall.include_needs_review`, `consolidate.revalidate`) and the counts summary in `memory://status` and the `consolidate()` report.
- No git dependency: revalidation hashes files, it does not read git objects or run subprocesses.
- No revalidation of `document` bodies against their source beyond the health pass's missing-source check.
- No per-chunk range invalidation: 0.4 hashes the whole source file, so any edit flags the whole snapshot; invalidating only the chunks whose byte range changed is a named follow-up ("per-chunk revalidation"), out of scope here.
- No new MCP tool; the ceiling is ten exclusive and 0.3 uses nine.
- No change to the `retain` / `get` / `forget` / `promote` / `ask` / `wiki_*` tool signatures; `recall` and `consolidate` gain one optional flag each.
- No migration of legacy shared chunk records and no source-kind metadata for documents; both are documented limitations.
- No reads outside the `project_root` boundary, ever.

## Key Entities

- **needs_review / review_reason**: additive memory metadata set by revalidation; `changed`, `missing`, or empty.
- **RevalidationReport**: the dict returned by `revalidate()` (counts plus `flagged` items).
- **code_chunk / parent_ref**: tag and owner link on the chunk records of a `code` memory, mirroring `document_chunk` / `document_id`; chunk records are owner-specific from 0.4 on.
- **superseded_by**: durable marker on a replaced record, set by auto-supersession and by explicit `supersedes`, propagated to owned chunks; `_filter_live`, `list_memories`, `consolidate` and `WikiExporter` treat a marked record as superseded regardless of the fetched set. Legacy links without the marker are reported as `unmarked_supersessions`.
- **HealthReport / HealthItem**: pydantic models; `summary` is the counts-only view used by the status resource and the consolidate report.
- **project_root**: the directory relative `source` paths resolve against.

## Success Criteria

1. US1 is demonstrable: retain a file as `code`, edit it on disk, run `consolidate(revalidate=True)`: the report lists the ref with reason `changed`; `recall` for a phrase in it returns nothing; `recall(include_needs_review=True)` returns it; `get` shows `needs_review=True`. Delete the file: reason `missing`. Restore the original: the flag clears.
2. US2 is demonstrable: retain a file twice with different content: `recall` returns only the newer ref even for a phrase present only in the old snapshot; `get(old)` shows the old content with `superseded_by` set; the old owned chunk records are gone while a chunk shared by content with the new version still exists under the new owner; retaining the same content again returns the newer ref unchanged; the same content retained under a second path is a separate record.
3. US3 is demonstrable on a store seeded with one of each defect: `health()` reports one item per category with the right ref_ids, `health(full=False)` omits `near_duplicates`, and `GET /health/store` returns the same report as JSON.
4. The session-start hook against an ephemeral store prints the 0.3 headings unchanged, and prints `### Needs review` and `### Store health` only when there is something to show.
5. `poetry run ruff check src/ tests/ templates/`, `poetry run ruff format --check src/ tests/`, `poetry run mypy src/` and `poetry run pytest -m "not slow" --cov=memkernel --cov-fail-under=80` pass; the registered MCP tools are exactly `retain, recall, get, forget, promote, consolidate, ask, wiki_export, wiki_import`.
6. `pyproject.toml` says `0.4.0` and `CHANGELOG.md` has the `[0.4.0]` section.

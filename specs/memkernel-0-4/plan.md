---
spec_mode: full
feature_id: memkernel-0-4
risk_category: feature
justification: "Two new public behaviours (revalidation with recall exclusion, read-only health pass) across core, storage metadata, MCP, admin API, lifecycle and templates; a full spec keeps the unattended build bounded."
status: draft
date: 2026-10-12
collaboration_mode: single
origin:
  issue: gosha70/memkernel#9
  urls:
    - https://github.com/gosha70/memkernel/issues/9
    - https://github.com/gosha70/memkernel/issues/10
    - https://github.com/gosha70/memkernel/issues/3
  transcripts:
    - specs/memkernel-0-4/origin/2026-10-12-decisions.md
  origin_claim: |
    Start working on the two issues left after closing #3 as superseded:
    #9 revalidate `code` memories when their source changes (mark
    `needs_review`, exclude from default recall, supersede on re-retain, no
    LLM or new dependency, plain file hashing) and #10 a deterministic,
    LLM-free store health pass (orphans, dangling links, stale sources,
    near-duplicates, expired-but-present; read-only, no new MCP tool).
    Ship both as one bundle, version 0.4.0; run revalidation through
    consolidate(revalidate=...) and at session start; auto-supersede code
    memories by source; expose health through Python, the admin API, the
    status resource and the consolidate report.
---

# Implementation Plan: memkernel 0.4 — code revalidation, store health pass

**Branch**: `feature/memkernel-0-4`
**Input**: specs/memkernel-0-4/spec.md

## Summary

0.3 can hold a snapshot of a file as a `code` memory but never notices when
the file changes, and nothing audits the store. 0.4 adds revalidation
(file-hash comparison, `needs_review` flag, recall exclusion, automatic
supersession on re-retain) and a read-only health pass (orphans, dangling
links, stale sources, needs-review, expired-but-present, near-duplicates),
both LLM-free and dependency-free, surfaced through the existing
`consolidate` tool, the session-start lifecycle, the admin API and the
status resource. No new MCP tool.

## Technical Context

**Language/Version**: Python 3.11–3.13, Poetry, pydantic 2, FastMCP (`mcp` 1.x), ChromaDB 1.5
**Primary Dependencies**: `src/memkernel/core/{models,services}.py`, `storage/chroma.py`, `lifecycle.py`, `mcp/tools/memory.py`, `mcp/server.py`, `api/routes/admin.py`, `config.py`, `templates/hooks/session-start.py`
**Testing**: `poetry run pytest -m "not slow" -q -p no:cacheprovider` with `tests/conftest.py::MockEmbedding` and `chromadb.EphemeralClient()`; files under `tmp_path`; e2e through `mcp.shared.memory.create_connected_server_and_client_session`
**Constraints**: no new runtime dependency; no git calls; MCP tool count stays nine; 0.1–0.3 stores load unchanged; coverage ≥ 80 percent; ruff line length 120; mypy strict

## Constitution Check

| Rule file | Concern | Status |
|-----------|---------|--------|
| `coding-standards.md` | No magic strings, no secrets, lint-clean | OK — reasons and tags are constants in `core/models.py`; thresholds are settings |
| `safety.md` | File access bounded, inputs validated | OK — only paths under `project_root` (or absolute) are read; nothing is written to disk; health never mutates |
| `copilot-conventions.md` | One logical change per commit, repo is source of truth | OK — one phase per commit |

## Architecture Decisions

### ADR-1: Revalidate by content hash, not by git

**Context**: issue #9 and the roadmap speak of git-diff-driven invalidation; `code` memories already store `content_hash` of the retained file text.
**Decision**: compare the current file's hash with `content_hash`; no git dependency, works in any checkout or none.
**Consequences**: a reformat counts as a change (acceptable: the snapshot is stale either way); 0.4 hashes whole files, per-chunk range invalidation is a named follow-up. `project_root` is a security boundary: sources are resolved with symlinks followed and `..` normalised and must lie under the resolved root; anything else is `unknown` and never read.

### ADR-2: `needs_review` is a flag, not a tier

**Context**: #3 proposed a `needs_review` state excluded from recall.
**Decision**: additive metadata on the record; `_filter_live` drops flagged records unless asked for; `get` and `list_memories` still show them.
**Consequences**: no schema change; old stores load with the default; the flag clears when the file matches again or when the memory is superseded.

### ADR-3: Sourced code identity is (source, hash); chunk records are owner-specific; supersession is durable

**Context**: today `code` records and their chunks are deduplicated globally by content hash, so two paths with the same content share one record and an unchanged function is one chunk shared by old and new versions; and `_filter_live` only hides a superseded record when its successor is in the same result window.
**Decision**: `find_by_hash` gains a `source` filter and sourced code dedups per path; chunk records get ids `<canonical>-chunk-<n>`, the `code_chunk` tag and `parent_ref`, and are written without dedup; the new canonical gets `supersedes=<old>` and every replaced canonical gets `superseded_by=<new>`, which `_filter_live` honours independently of the window; `revalidate()` backfills the marker for 0.2/0.3 links. Old canonicals stay (hidden); only their owned chunks are deleted.
**Consequences**: provenance survives, recall stays clean for any query, flags and deletions can never touch another owner's chunks; the store holds one chunk record per owner (bounded by the number of live snapshots since replaced owners lose theirs). Legacy shared chunks are left as they are and documented.

### ADR-4: Health is read-only and split into quick and full

**Context**: near-duplicate detection re-embeds and queries each long-term memory; the status resource and `consolidate` must stay cheap; the pass must be complete within its candidate set.
**Decision**: `health(full=False)` for the summary paths (status, consolidate, session start); `health()` for the admin endpoint and curators. Near-duplicates query each candidate with `top_k = health_duplicate_limit` restricted to the long-term tier and keep only neighbours inside the candidate set, so every qualifying pair in the set is found. `stale_sources` covers `code` memories only: a `document` source is a name, not a path.
**Consequences**: the hooks cost O(n) metadata reads, not O(n) embeddings; the full pass is O(n) queries bounded by the limit; a fix mode is a later feature.

## Project Structure

```
src/memkernel/config.py                   — project_root, health_* settings
src/memkernel/core/models.py              — needs_review/review_reason/superseded_by on Memory; CODE_CHUNK_TAG, PARENT_REF_KEY; review reasons; HealthReport, HealthItem
src/memkernel/core/services.py            — revalidate(), auto-supersession in retain(code), recall include_needs_review, consolidate(revalidate, health), health()
src/memkernel/storage/chroma.py           — load needs_review / review_reason / superseded_by; find_by_hash(source)
src/memkernel/lifecycle.py                — Needs review + Store health sections at session start
src/memkernel/mcp/tools/memory.py         — recall include_needs_review, consolidate revalidate
src/memkernel/mcp/server.py               — health summary in memory://status
src/memkernel/api/routes/admin.py         — POST /revalidate, GET /health/store
tests/unit/test_revalidation.py, test_code_supersession.py, test_health.py; test_admin_api.py, test_lifecycle_component.py additions
tests/e2e/test_mcp_roundtrip.py           — code revalidation round trip
README.md, CHANGELOG.md, pyproject.toml, src/memkernel/__init__.py, docs/roadmap.md, docs/architecture/memory-tiers.md, templates/claude-memory-instructions.md
```

## Scope

### Task 1: Revalidation (US1)

**Files**: `config.py`, `core/models.py`, `storage/chroma.py`, `core/services.py`, `lifecycle.py`, `mcp/tools/memory.py`, `api/routes/admin.py`, tests
**Acceptance criteria**:
- [ ] FR-001, FR-002, FR-003, FR-004, FR-005, FR-006 implemented
- [ ] `tests/unit/test_revalidation.py` covers changed / missing / cleared / unknown, chunk propagation, recall exclusion and flag, consolidate report, lifecycle section, admin endpoint

### Task 2: Code identity, owner-specific chunks, durable supersession (US2)

**Files**: `core/ports.py`, `storage/chroma.py`, `core/models.py`, `core/services.py`, tests
**Acceptance criteria**:
- [ ] FR-007, FR-008 implemented; `_filter_live` honours `superseded_by` (FR-004)
- [ ] `tests/unit/test_code_supersession.py` covers changed content, identical content same path, identical content other path, empty source, shared-by-content chunk kept under the new owner, old-only phrase hidden after supersession, several pre-0.4 live canonicals, legacy `chunk_refs` deletion rule, explicit `supersedes` sets the marker; e2e round trip added

### Task 3: Health pass (US3)

**Files**: `core/models.py`, `core/services.py`, `api/routes/admin.py`, `mcp/server.py`, `lifecycle.py`, tests
**Acceptance criteria**:
- [ ] FR-009, FR-010, FR-011, FR-012 implemented
- [ ] `tests/unit/test_health.py` seeds one defect per category and checks the report, the quick/full split, the endpoint, the resource and the consolidate summary

### Task 4: Release hygiene (US4)

**Files**: `pyproject.toml`, `src/memkernel/__init__.py`, `CHANGELOG.md`, `README.md`, `docs/roadmap.md`, `docs/architecture/memory-tiers.md`, `docs/adr/ADR-007-tiered-memory.md` (supersession note only), `templates/claude-memory-instructions.md`
**Acceptance criteria**:
- [ ] FR-013, FR-014 (coverage), FR-015 satisfied
- [ ] Full fast suite, ruff, ruff format, mypy green; `poetry build` succeeds

# Tasks: Code-Aware Memory Server MVP

<!-- Generated from spec.md. One owner per file. -->
<!-- [P] = can run in parallel with other [P] tasks in the same story group. -->
<!-- [US#] = traceability tag linking back to spec.md user story. -->

## Bootstrap: Project skeleton

| # | [P] | Task | File(s) | Owner | Done |
|---|-----|------|---------|-------|------|
| 0 | | pyproject.toml, src/memkernel/__init__.py, tests/, eval/ dirs, CI setup | `pyproject.toml`, package skeleton | QA Engineer | [ ] |

**Checkpoint Bootstrap** — verify before continuing:
- [ ] `poetry install` succeeds
- [ ] `poetry run pytest` runs (no tests yet, but framework works)
- [ ] `ruff check . && mypy src/` passes on empty package

---

## US1+US2: Core memory round-trip (retain → recall → get)

| # | [P] | Task | File(s) | Owner | Done |
|---|-----|------|---------|-------|------|
| 1 | | Core domain models + protocols (ArtifactRef includes type + timestamp; SparseIndexPort added) | `core/models.py`, `core/ports.py`, `config.py` | Team Lead | [ ] |
| 2 | [P] | ChromaDB storage adapter (dense search only — no sparse at this layer) | `storage/chroma.py` | Storage Engineer | [ ] |
| 3 | [P] | Embedding adapter | `retrieval/embeddings.py` | Retrieval Engineer | [ ] |
| 4 | [P] | BM25 side index (rank_bm25, add/remove/search, rebuild from ChromaDB on startup) | `retrieval/sparse.py` | Retrieval Engineer | [ ] |
| 5 | | Hybrid search engine — queries dense + sparse, fuses via RRF (depends on #2, #3, #4) | `retrieval/search.py` | Retrieval Engineer | [ ] |
| 6 | | Memory service — orchestrates retain/recall/forget/get, writes to both ChromaDB AND BM25, dedup per ADR-5, session_id per ADR-6 (depends on #1, #2, #3, #4, #5) | `core/services.py`, `memory/types.py`, `memory/lifecycle.py`, `memory/dedup.py` | Storage Engineer | [ ] |
| 7 | | MCP server + tools — retain(type, session_id, checkpoint), recall(type, session_id, checkpoint_only filters), forget, get (depends on #6) | `mcp/server.py`, `mcp/tools/memory.py` | MCP Engineer | [ ] |

**Checkpoint US1+US2** — verify before continuing:
- [ ] MCP client can retain a memory with type + session_id, recall it by query, get full content by ref_id
- [ ] `recall` returns ArtifactRef (ref_id, preview, score, token_count, type, timestamp — not full content)
- [ ] `recall` with type filter returns only matching MemoryType
- [ ] `recall` with session_id filter returns only matching session
- [ ] Per-project collection isolation works (two projects don't cross-contaminate)
- [ ] Content dedup: retaining the same content + same type twice returns the same ref_id but updates session_id, timestamp, and checkpoint (ADR-5)
- [ ] Content dedup: retaining the same content with a different type creates a new memory with a different ref_id (ADR-5)
- [ ] `forget` removes from both ChromaDB and BM25 index
- [ ] mypy strict passes, ruff clean

---

## US3: AST-aware code indexing

| # | [P] | Task | File(s) | Owner | Done |
|---|-----|------|---------|-------|------|
| 8 | | Tree-sitter AST chunking + contextual augmentation (scope + imports prepended) | `retrieval/chunking.py` | Retrieval Engineer | [ ] |
| 9 | | Integration: chunking → embedding → store pipeline (updates to MemoryService) | `core/services.py` | Storage Engineer | [ ] |

**Checkpoint US3** — verify before continuing:
- [ ] Python and TypeScript files chunk at function/class boundaries
- [ ] No chunk splits a function mid-body
- [ ] Unsupported languages fall back to token-based splitting
- [ ] Chunks have language, file_path, ast_node_type metadata

---

## US4: Post-compaction context recovery

| # | [P] | Task | File(s) | Owner | Done |
|---|-----|------|---------|-------|------|
| 10a | | Checkpoint support in MCP tool definitions (checkpoint flag + checkpoint_only filter params) | `mcp/tools/memory.py` | MCP Engineer | [x] |
| 10b | | Checkpoint support in MemoryService (checkpoint storage as type=episode, checkpoint_only query logic) | `core/services.py` | Team Lead | [x] |
| 11 | [P] | CLAUDE.md memory instructions template (pre/post-compaction instructions) | `templates/claude-memory-instructions.md` | Team Lead | [x] |
| 12 | [P] | Hook templates: PreCompact → retain(checkpoint=true), PostCompact → recall(checkpoint_only=true) | `templates/hooks/` | MCP Engineer | [x] |
| 13 | | E2E test: store decisions + checkpoint → simulate compaction → recall recovers both | `tests/e2e/` | QA Engineer | [x] |

**Checkpoint US4** — verify before continuing:
- [x] `retain(checkpoint=true)` stores a structured snapshot as type=episode
- [x] `recall(checkpoint_only=true)` returns only checkpoint memories, most recent first
- [x] After simulated compaction, recall recovers both checkpoint and decisions
- [x] Hook templates (Python scripts) are syntactically valid and ruff/mypy clean
- [x] CLAUDE.md template includes pre/post-compaction instructions

---

## US5: Hybrid search quality

| # | [P] | Task | File(s) | Owner | Done |
|---|-----|------|---------|-------|------|
| 14 | [P] | Eval dataset creation (20+ labeled query-answer pairs) | `eval/datasets/` | QA Engineer | [ ] |
| 15 | [P] | Eval harness (recall@k, precision@k, MRR, ablations) | `eval/run_eval.py` | QA Engineer | [ ] |
| 16 | | Run eval, tune RRF k parameter | `eval/` | Retrieval Engineer | [ ] |

**Checkpoint US5** — verify before continuing:
- [ ] Hybrid search outperforms dense-only and BM25-only on eval dataset
- [ ] recall@5 >= 0.7, MRR >= 0.5

---

## US6+US7: Forget + isolation

| # | [P] | Task | File(s) | Owner | Done |
|---|-----|------|---------|-------|------|
| 17 | [P] | Forget implementation + tests (deletes from ChromaDB + BM25) | `core/services.py`, `tests/unit/` | Storage Engineer | [ ] |
| 18 | [P] | Cross-project isolation test | `tests/integration/` | QA Engineer | [x] |

**Checkpoint US6+US7** — verify before continuing:
- [x] `forget(ref_id)` removes memory from both ChromaDB and BM25 index
- [x] Forgotten memory no longer appears in search results
- [x] Cross-project contamination test passes

---

## Infrastructure

| # | [P] | Task | File(s) | Owner | Done |
|---|-----|------|---------|-------|------|
| 19 | [P] | FastAPI admin API (/health, /collections, /stats) | `api/app.py`, `api/routes/admin.py` | MCP Engineer | [ ] |
| 20 | | README with install + usage instructions | `README.md` | Team Lead | [ ] |

**Checkpoint Infrastructure** — verify before continuing:
- [ ] `poetry install && poetry run pytest` passes
- [ ] `/health` returns valid status
- [ ] README covers: install as MCP server, basic usage, configuration

---

## Final Verification

- [ ] Type checker: 0 errors (mypy strict)
- [ ] Linter: 0 errors (ruff)
- [ ] All existing tests pass
- [ ] No [NEEDS CLARIFICATION] markers remain in spec.md
- [ ] MCP tool count < 10
- [ ] E2E round-trip: install as MCP server in Claude Code, retain → recall → get → forget
- [ ] Eval metrics meet thresholds (recall@5 >= 0.7, MRR >= 0.5)
- [ ] Dedup test: identical content + type returns same ref_id, refreshes session_id, timestamp, and checkpoint
- [ ] Dedup test: identical content + different type creates separate ref_id
- [ ] Session filter test: recall with session_id returns only that session's memories
- [ ] Checkpoint round-trip: retain(checkpoint) → recall(checkpoint_only) recovers snapshot

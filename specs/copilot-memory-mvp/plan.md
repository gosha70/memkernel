---
spec_mode: full
feature_id: copilot-memory-mvp
risk_category: integration
justification: "New product with MCP protocol integration, vector DB, AST parsing, and hybrid retrieval — touches multiple integration boundaries"
status: draft
date: 2026-03-18
collaboration_mode: single
---

# Implementation Plan: Code-Aware Memory Server MVP

**Branch**: `feature/copilot-memory-mvp`
**Input**: specs/copilot-memory-mvp/spec.md

## Summary

Build an MCP-native memory server that enables AI coding copilots to persist and retrieve project knowledge across sessions. The server uses tree-sitter for AST-aware code chunking, ChromaDB for hybrid vector+sparse search, and the reference-based return pattern (IDs + previews, not full content) to minimize client context window consumption. This is the MVP — code-aware RAG without learning loops, git integration, or convention auto-detection.

## Technical Context

**Language/Version**: Python 3.11–3.13 (`>=3.11,<3.14` — cap is temporary until PyTorch ships Python 3.14 wheels for a patched release; CVE-2025 in torch ≤2.7.1 forces the bound)
**Primary Dependencies**: MCP SDK (mcp), ChromaDB, tree-sitter, tree-sitter-languages, sentence-transformers (or configurable), Pydantic, FastAPI (admin only)
**Testing**: pytest with unit/integration/e2e markers
**Constraints**:
- Tool count < 10 (minimize context window overhead)
- ChromaDB only for MVP (no Qdrant/pgvector yet)
- No frontend, no auth, no multi-tenancy
- Must work as stdio MCP server for Claude Code and Streamable HTTP for remote use

## Constitution Check

| Rule file | Concern | Status |
|-----------|---------|--------|
| `coding-standards.md` | No magic strings, no secrets, lint-clean | OK — all config via Pydantic settings, embedding model in config |
| `safety.md` | No credentials in source, inputs validated | OK — no auth in MVP, API keys via env vars only |
| `copilot-conventions.md` | One logical change per commit, repo is source of truth | OK |

## Architecture Decisions

### ADR-1: MCP-first, FastAPI secondary

**Context**: The server needs to be consumable by Claude Code, Cursor, and other MCP-compatible tools. It also needs admin/debug endpoints.
**Decision**: MCP server is the primary interface (tools: retain, recall, forget, get). FastAPI serves admin endpoints only (collection stats, health, memory browser). Both share the same core services.
**Consequences**: MCP tool definitions must be kept minimal. FastAPI routes are optional and don't need to mirror MCP tools exactly.

### ADR-2: ChromaDB for MVP with application-level BM25

**Context**: Need a vector store with hybrid search support. Options: ChromaDB (zero-config, embedded), Qdrant (production-grade, native sparse vectors), pgvector (relational). ChromaDB provides dense vector search but does not natively expose a BM25 sparse index.
**Decision**: ChromaDB for MVP — embedded mode, no infrastructure dependency, fast iteration. BM25 sparse search is implemented as an **application-level side index** in `retrieval/sparse.py` using `rank_bm25`, maintained alongside ChromaDB. Plan migration path to pgvector when relational metadata queries become critical.
**Consequences**: The BM25 index is a separate in-memory structure. ChromaDB is the authoritative store; the BM25 index is a derived, rebuildable cache. Consistency model:
- **`retain`**: write to ChromaDB first (authoritative). If ChromaDB succeeds, add to BM25 index. If the BM25 add fails, log the error — the record exists in ChromaDB and will be picked up on next rebuild. Dense search still works; sparse search misses the entry until rebuild.
- **`forget`**: delete from ChromaDB first (authoritative). If ChromaDB succeeds, remove from BM25 index. If the BM25 remove fails, log the error — the BM25 index may return a stale hit whose `get(ref_id)` will return "not found", which the caller handles. The stale entry is cleaned on next rebuild.
- **Rebuild**: The BM25 index is fully rebuilt from ChromaDB on server startup and can be triggered via an admin endpoint (`POST /admin/rebuild-index`). This is the consistency recovery mechanism — any drift between the two stores is resolved by rebuild.
- **Design invariant**: ChromaDB is always correct. BM25 may lag but never contradicts ChromaDB in a way that produces incorrect data — at worst it produces stale refs that resolve to "not found".
RRF fusion lives in `retrieval/search.py` (service layer, not the storage adapter) — it receives ranked lists from both backends and merges them. This separation means neither ChromaDB adapter nor BM25 index knows about the other; `HybridSearchService` orchestrates both.

### ADR-3: Embedding model selection

**Context**: Need embeddings for code and natural language memories. Options: sentence-transformers (local, free), Voyage Code (code-specific, paid), OpenAI text-embedding-3-small (general, paid).
**Decision**: Default to `all-MiniLM-L6-v2` via sentence-transformers for MVP (local, zero-cost, fast). Make the embedding model configurable via settings so users can swap to Voyage Code or OpenAI.
**Consequences**: Local-first means no API key required for basic use. Code-specific models may improve retrieval quality — measure in eval before recommending a switch.

### ADR-4: Reference-based returns

**Context**: MCP tool responses flow through the client's context window. Large responses waste tokens.
**Decision**: `recall` returns `ArtifactRef` objects (ref_id, preview ~200 chars, score, token_count, type, timestamp). Full content requires a separate `get(ref_id)` call. The `type` and `timestamp` fields are required per FR-003 so clients can filter/sort without fetching full content.
**Consequences**: Two-step retrieval flow. Clients must call `get` for full content. Reduces per-search token cost by 80-95%. ArtifactRef carries enough metadata for client-side filtering.

### ADR-5: Deduplication semantics — content hash vs ref_id identity

**Context**: FR-010 requires dedup by content hash. But each Memory has a unique ref_id, and `forget(ref_id)` deletes one memory. If two `retain` calls send identical content, what happens? Options: (a) return the existing ref_id (idempotent), (b) create a second metadata-only record sharing content, (c) reject the duplicate.
**Decision**: **Content+type-scoped dedup within a project, with metadata refresh.** The dedup key is `(content_hash, type)`. When `retain` is called with content whose SHA-256 hash and `type` already match an existing record in the same project's collection, the system returns the existing `ref_id` and **updates mutable metadata** (`session_id`, `timestamp`, `checkpoint`) to the new values. The content and `ref_id` stay the same — no re-embedding occurs. Same content with a **different `type`** creates a separate memory with its own `ref_id` — a decision and an episode with identical text are semantically different records.
**Consequences**: `retain` is idempotent for content+type (no duplicate storage or embedding cost) but keeps provenance fresh — the same decision retained in a later session will appear under that session's `session_id` filter and carry the latest timestamp. Checkpoints with unchanged content still update their recency and `checkpoint` flag. `forget(ref_id)` is safe — it deletes exactly one record since there are no aliases or shared content references. Cross-project dedup is not performed (project isolation takes priority). The BM25 side index mirrors this: one entry per ref_id, content unchanged on metadata refresh (no BM25 re-index needed).

### ADR-6: Session scoping in tool contract

**Context**: FR-009 requires `session_id` metadata, and episodic memories need session-scoped TTL. But the MCP tool parameters don't specify how `session_id` is supplied, and `recall` doesn't distinguish episodic from durable memories.
**Decision**: `retain` accepts an optional `session_id` parameter (string). If omitted, defaults to `"default"`. `retain` also accepts a required `type` parameter (MemoryType enum: decision/convention/code/episode). `recall` accepts optional `type` and `session_id` filter parameters — when provided, results are filtered to matching metadata before ranking. Episodic memories (type=episode) are scoped to their session for TTL purposes but are searchable across sessions unless filtered.
**Consequences**: Session scoping is opt-in via filter, not enforced by separate collections. This keeps the storage model simple (one collection per project) while allowing session-aware queries. TTL enforcement uses `type` + `timestamp` to identify expired records, not session boundaries. Copilots that want session-isolated recall pass `session_id` as a filter.

## Project Structure

```
src/memkernel/
├── __init__.py                — Package version + public API
├── config.py                  — Pydantic settings (env vars, defaults)
├── mcp/
│   ├── server.py              — MCP server lifecycle, tool registration
│   └── tools/
│       ├── memory.py          — retain, recall, forget, get tools
│       └── admin.py           — status, collections tools (if needed)
├── core/
│   ├── models.py              — Memory, CodeChunk, ArtifactRef, MemoryType
│   ├── services.py            — MemoryService (retain, recall, forget, get logic)
│   └── ports.py               — VectorStorePort, EmbeddingPort, ChunkerPort, SparseIndexPort protocols
├── storage/
│   ├── chroma.py              — ChromaDB adapter implementing VectorStorePort
│   └── migrations/            — Future schema migrations
├── retrieval/
│   ├── chunking.py            — tree-sitter AST-aware chunking + token-based fallback
│   ├── embeddings.py          — EmbeddingAdapter (sentence-transformers default)
│   ├── sparse.py              — BM25 side index (rank_bm25, rebuilt from ChromaDB on startup)
│   └── search.py              — HybridSearchService: queries dense + sparse, fuses via RRF
├── memory/
│   ├── types.py               — MemoryType enum, TTL policies per type
│   ├── lifecycle.py           — TTL enforcement, eviction, importance scoring
│   └── dedup.py               — SHA-256 content deduplication
├── api/
│   ├── app.py                 — FastAPI admin instance
│   └── routes/
│       └── admin.py           — /health, /collections, /stats
tests/
├── unit/                      — Component tests (mocked vector store)
├── integration/               — Tests with real ChromaDB
└── e2e/                       — MCP client round-trip tests
eval/
├── datasets/                  — Labeled retrieval test sets
└── run_eval.py                — recall@k, precision@k, MRR, hybrid ablations
doc_internal/
├── claude-memory-instructions.md  — CLAUDE.md template for copilot memory integration
└── hooks/                     — PreCompact / PostCompact hook templates
pyproject.toml                 — Project metadata, dependencies, tool config
```

## Scope

### Task 1: Core domain models and protocols

**Files**: `src/memkernel/core/models.py`, `src/memkernel/core/ports.py`, `src/memkernel/config.py`
**Acceptance criteria**:
- [ ] Memory, CodeChunk, ArtifactRef, MemoryType models defined with Pydantic
- [ ] ArtifactRef includes: ref_id, preview, score, token_count, type (MemoryType), timestamp (datetime)
- [ ] VectorStorePort, EmbeddingPort, ChunkerPort, SparseIndexPort protocols defined
- [ ] Pydantic settings with configurable: embedding model, chunk size, ChromaDB path, project_id, default session_id
- [ ] mypy strict passes

### Task 2: ChromaDB storage adapter

**Files**: `src/memkernel/storage/chroma.py`
**Acceptance criteria**:
- [ ] Implements VectorStorePort protocol (dense search only — no sparse/hybrid at this layer)
- [ ] upsert, search_dense (vector similarity), delete, get_by_id, list_all operations
- [ ] Per-project collection isolation (collection name includes project_id)
- [ ] Content dedup by SHA-256 hash + type on upsert (see ADR-5 for dedup semantics)
- [ ] Integration tests pass against real ChromaDB

### Task 3: Tree-sitter AST chunking

**Files**: `src/memkernel/retrieval/chunking.py`
**Acceptance criteria**:
- [ ] Parses Python, TypeScript, JavaScript, Java, Go, Rust via tree-sitter
- [ ] Chunks align to function/class/method boundaries (never splits mid-body)
- [ ] Each chunk has contextual augmentation: scope path + imports prepended to embedding text
- [ ] Falls back to token-based splitting for unsupported languages
- [ ] Unit tests verify boundary alignment on sample files

### Task 4: Embedding adapter

**Files**: `src/memkernel/retrieval/embeddings.py`
**Acceptance criteria**:
- [ ] Implements EmbeddingPort protocol
- [ ] Default: sentence-transformers `all-MiniLM-L6-v2` (local, no API key)
- [ ] Model name configurable via settings
- [ ] Batch embedding support for bulk indexing
- [ ] Unit tests with deterministic output verification

### Task 5: BM25 side index + hybrid search engine

**Files**: `src/memkernel/retrieval/sparse.py`, `src/memkernel/retrieval/search.py`
**Acceptance criteria**:
- [ ] `sparse.py`: BM25 index using `rank_bm25` library, rebuilt from ChromaDB on server startup
- [ ] `sparse.py`: `add`, `remove`, `search` methods that maintain index consistency
- [ ] `search.py`: `HybridSearchService` queries ChromaDB (dense) and BM25 index (sparse) independently
- [ ] `search.py`: RRF fusion merges both ranked lists with configurable k parameter (default k=60)
- [ ] Returns ranked list of ArtifactRef objects (ref_id, preview, score, token_count, type, timestamp)
- [ ] Configurable top_k with default of 5
- [ ] Unit tests for RRF fusion logic; unit tests for BM25 index add/remove consistency
- [ ] Integration tests for end-to-end hybrid search against real ChromaDB + BM25

### Task 6: Memory service (core business logic)

**Files**: `src/memkernel/core/services.py`, `src/memkernel/memory/types.py`, `src/memkernel/memory/lifecycle.py`, `src/memkernel/memory/dedup.py`
**Acceptance criteria**:
- [ ] MemoryService orchestrates: retain (chunk + embed + store to ChromaDB AND BM25 index), recall (hybrid search with optional type/session_id filters), forget (delete from ChromaDB AND BM25 index), get (fetch by ref_id)
- [ ] `retain` accepts required `type` (MemoryType) and optional `session_id` (default: "default")
- [ ] `recall` accepts optional `type` and `session_id` filter params — applied as metadata filters before ranking
- [ ] Metadata stamped on every memory: project_id, session_id, timestamp, type, source, hash, token_count
- [ ] Deduplication per ADR-5: identical content hash + type within a project returns existing ref_id (no re-embedding), but updates mutable metadata (session_id, timestamp, checkpoint) to caller's values. Same content with different type creates a new memory.
- [ ] `forget` deletes from ChromaDB first (authoritative), then removes from BM25 index. If BM25 remove fails, log error and continue — stale BM25 entry resolves to "not found" on `get`, cleaned on next rebuild
- [ ] TTL policies defined per MemoryType (decisions: no expiry, episodes: configurable TTL)
- [ ] Unit tests with mocked VectorStorePort and SparseIndexPort

### Task 7: Compaction recovery — checkpoint tool + hook template

**Files**: `src/memkernel/mcp/tools/memory.py`, `doc_internal/claude-memory-instructions.md`, `doc_internal/hooks/`
**Acceptance criteria**:
- [ ] `retain` supports a `checkpoint` flag — when true, stores a structured snapshot of active task state (open questions, decisions made, files touched, pending work) as a single memory with type=episode
- [ ] `recall` supports a `checkpoint_only` filter — returns only checkpoint memories, most recent first
- [ ] CLAUDE.md template includes: (a) instruction to call `retain(checkpoint=true)` before compaction, (b) instruction to call `recall(checkpoint_only=true)` after compaction to re-inject context
- [ ] Hook template provided: a PreCompact hook script that calls `retain(checkpoint=true)` via MCP, and a PostCompact hook script that calls `recall(checkpoint_only=true)` and injects results
- [ ] E2E test: store 5+ decisions + 1 checkpoint → simulate compaction → recall with checkpoint_only recovers the checkpoint → recall with query recovers decisions

### Task 8: MCP server and tools

**Files**: `src/memkernel/mcp/server.py`, `src/memkernel/mcp/tools/memory.py`
**Acceptance criteria**:
- [ ] MCP server starts via stdio and Streamable HTTP transports
- [ ] Tools registered: `retain` (with type, session_id, checkpoint params), `recall` (with type, session_id, checkpoint_only filters), `forget`, `get` (4 tools)
- [ ] Health exposed as MCP resource (not tool)
- [ ] Tool definitions are concise (short descriptions, typed params with defaults)
- [ ] `recall` returns ArtifactRef list (ref_id, preview, score, token_count, type, timestamp); `get` returns full content
- [ ] Total tool count < 10
- [ ] E2E test: MCP client round-trip (retain → recall → get → forget)

### Task 9: FastAPI admin API

**Files**: `src/memkernel/api/app.py`, `src/memkernel/api/routes/admin.py`
**Acceptance criteria**:
- [ ] `/health` returns server status, collection count, memory count
- [ ] `/collections` lists project collections with sizes
- [ ] `/stats` returns retrieval timing, memory growth metrics
- [ ] Not required for MCP operation — purely optional

### Task 10: Eval harness

**Files**: `eval/run_eval.py`, `eval/datasets/`
**Acceptance criteria**:
- [ ] Labeled dataset with at least 20 query-answer pairs (code + natural language)
- [ ] Metrics: recall@5, precision@5, MRR
- [ ] Hybrid ablation: dense-only vs BM25-only vs hybrid RRF
- [ ] Pass thresholds: recall@5 >= 0.7, MRR >= 0.5

## Constraints / What NOT to Build

- No git integration — deferred to Phase 2
- No convention auto-detection — deferred to Phase 2
- No knowledge graph — deferred to Phase 2
- No reflective learning / RLM — deferred to Phase 3
- No pgvector/Qdrant backends — deferred to Phase 4
- No multi-tenancy / auth — deferred to Phase 4
- No cross-encoder reranking — add only if eval shows it's needed
- No frontend / UI of any kind

## File Ownership (Non-Overlapping)

| Owner | Files |
|-------|-------|
| Team Lead | `core/models.py`, `core/ports.py`, `core/services.py`, `config.py` |
| MCP Engineer | `mcp/server.py`, `mcp/tools/`, `doc_internal/hooks/` |
| Retrieval Engineer | `retrieval/chunking.py`, `retrieval/embeddings.py`, `retrieval/sparse.py`, `retrieval/search.py` |
| Storage Engineer | `storage/chroma.py`, `memory/types.py`, `memory/lifecycle.py`, `memory/dedup.py` |
| QA Engineer | `tests/`, `eval/` |

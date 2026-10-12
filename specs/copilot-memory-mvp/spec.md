---
spec_mode: full
feature_id: copilot-memory-mvp
risk_category: integration
status: draft
date: 2026-03-18
---

# Spec: Code-Aware Memory Server for AI Coding Copilots (MVP)

<!-- Project constitution: shared/rules/always/ — copilot-conventions.md, coding-standards.md, safety.md -->

## User Scenarios

### US1: Developer installs and retains a memory (Priority: HIGH)

**Given** a developer has installed memkernel as an MCP server in Claude Code (or Cursor)
**When** they complete a significant architectural decision during a coding session
**Then** the copilot calls the `retain` tool to persist that decision with project context, and the memory is stored in a project-scoped collection with metadata (timestamp, type, source, hash)

### US2: Developer recalls memory in a new session (Priority: HIGH)

**Given** a developer starts a new coding session on the same project
**When** the copilot encounters a task related to a previously stored decision
**Then** calling `recall` with a natural-language query returns relevant memories as ref_id + preview pairs (not full content), ranked by hybrid search (dense + BM25 + RRF)

### US3: AST-aware code chunks are indexed automatically (Priority: HIGH)

**Given** a developer points memkernel at a codebase directory
**When** the system indexes the code
**Then** files are parsed via tree-sitter into AST-aligned chunks (functions, classes, methods — never splitting mid-body), each chunk is embedded with scope/import context prepended, and stored with language, file path, and AST node type metadata

### US4: Critical context survives compaction (Priority: HIGH)

**Given** a long coding session triggers Claude Code's auto-compaction
**When** the copilot's CLAUDE.md instructs it to call `recall` after compaction
**Then** previously stored decisions, conventions, and code context are retrieved and re-injected, preventing the "compaction drift" where project rules are lost

### US5: Developer searches with mixed intent (Priority: MEDIUM)

**Given** memories contain both exact identifiers (function names, error codes) and semantic concepts (architectural patterns, design decisions)
**When** a developer searches for "the auth middleware we decided to replace"
**Then** hybrid search returns results matching both the keyword "auth middleware" (BM25) and the semantic concept of replacement decisions (dense), fused via RRF

### US6: Developer forgets outdated memories (Priority: MEDIUM)

**Given** a stored memory is no longer accurate (e.g., a convention was reversed)
**When** the developer or copilot calls `forget` with a ref_id
**Then** the memory is removed from the vector store and no longer appears in search results

### US7: Per-project isolation (Priority: HIGH)

**Given** a developer works on multiple projects
**When** they search memories while in project A
**Then** only memories from project A's collection are returned; project B's memories are never contaminated into results

## Requirements

- **FR-001**: System MUST expose an MCP server supporting both stdio and Streamable HTTP transports
- **FR-002**: System MUST provide these MCP tools: `retain` (store memory — accepts required `type` param, optional `session_id`, optional `checkpoint` bool), `recall` (search memories — accepts optional `type`, `session_id`, and `checkpoint_only` filters), `forget` (delete memory by ref_id), `get` (retrieve full content by ref_id)
- **FR-003**: `recall` MUST return reference-based results: `ref_id`, `preview` (first ~200 chars), `score`, `token_count`, `type`, `timestamp` — never full content
- **FR-004**: `get` MUST accept a `ref_id` and return the full memory content
- **FR-005**: System MUST support hybrid search combining dense embeddings + BM25 sparse search, fused via Reciprocal Rank Fusion (RRF)
- **FR-006**: System MUST chunk code files using tree-sitter AST parsing, aligning boundaries to complete syntactic units (functions, classes, methods)
- **FR-007**: Each code chunk MUST be embedded with contextual augmentation: scope path, import statements, and entity signatures prepended to the chunk text
- **FR-008**: System MUST store per-project collections with isolation — collection names include project identifier
- **FR-009**: Every stored memory item MUST carry metadata: `project_id`, `session_id`, `timestamp`, `type` (decision/convention/code/episode), `source`, `hash` (SHA-256), `token_count`
- **FR-010**: System MUST deduplicate on upsert by content hash **and type** within a project — identical content with the same `type` returns the existing `ref_id` without re-embedding or creating a new record, but MUST update mutable metadata (`session_id`, `timestamp`, `checkpoint`) to the caller's values. Same content with a different `type` creates a separate memory (different ref_id). Cross-project dedup is not performed.
- **FR-011**: System MUST use ChromaDB as the vector store backend for MVP
- **FR-012**: System MUST expose a health MCP resource reporting server status, collection count, and memory item count
- **FR-013**: Tool count MUST remain under 10 total to minimize context window overhead in client copilots
- **FR-014**: System MUST support configurable embedding models via config (not hardcoded)
- **FR-015**: System MUST support TTL/eviction policies that are type-dependent (ephemeral episodes expire faster than durable decisions)

## Constraints / What NOT to Build

- No reflective learning loop (RLM) — deferred to Phase 3
- No multi-tenancy or authentication — deferred to Phase 4
- No pgvector or Qdrant backend — MVP uses ChromaDB only; migration path planned
- No frontend UI — headless MCP server only
- No convention auto-detection from codebase patterns — deferred to Phase 2
- No git history indexing (commits, blame, diffs) — deferred to Phase 2
- No knowledge graph or entity relationship tracking — deferred to Phase 2
- No cross-encoder reranking in MVP — add when retrieval eval shows it's needed

## Key Entities

- **Memory**: A stored unit of knowledge — can be a decision, convention, code pattern, or session episode. Has content, metadata, and a unique ref_id.
- **CodeChunk**: An AST-aligned fragment of source code, produced by tree-sitter parsing. Carries language, file path, AST node type, scope context.
- **Project**: An isolation boundary. Each project has its own ChromaDB collection(s). Identified by `project_id`.
- **Session**: A single copilot conversation session. Memories are tagged with `session_id` for provenance.
- **ArtifactRef**: A lightweight reference to a memory (ref_id + preview + score + token_count + type + timestamp), returned by `recall` instead of full content.
- **MemoryType**: Enum — `decision`, `convention`, `code`, `episode`. Controls TTL/eviction policy.

## Success Criteria

1. US1+US2: Round-trip memory flow demonstrated — retain in session 1, recall in session 2 returns the stored memory
2. US3: Python and TypeScript files are chunked at function/class boundaries (not mid-body) as verified by manual inspection of 10+ files
3. US4: After simulated compaction, `recall` retrieves decisions stored earlier in the same session
4. US5: Hybrid search returns results that pure dense or pure BM25 alone would miss, demonstrated on a labeled eval dataset
5. US7: Cross-project contamination test passes — searching project A never returns project B memories
6. FR-013: Total MCP tool count is under 10
7. FR-003: `recall` never returns content exceeding preview length; full content requires explicit `get` call
8. No regressions: existing test suite passes

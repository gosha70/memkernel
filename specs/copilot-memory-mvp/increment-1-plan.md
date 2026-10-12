# Plan: First Increment — Bootstrap + Core Memory Round-Trip (Tasks 0–7)

## Context

MemKernel is a code-aware memory server for AI coding copilots. The repo currently has zero source code — only specs, research docs, and CLAUDE.md. This increment takes it from empty to a working MCP server supporting `retain`, `recall`, `get`, and `forget` with hybrid search (dense + BM25 + RRF). AST chunking (US3) is NOT in scope — `retain` stores text directly.

**Source spec**: `specs/copilot-memory-mvp/tasks.md` → Bootstrap + US1+US2
**Branch**: `feature/copilot-memory-mvp`

### Spec amendments applied

**FR-010 (dedup scope)**: Amended to `(content_hash, type)` dedup key. `spec.md` FR-010, `plan.md` ADR-5, and `tasks.md` acceptance criteria all updated. Same content with different `type` creates a separate memory. Mutable metadata on dedup hit: `session_id`, `timestamp`, `checkpoint`.

---

## Step 0: Bootstrap — Project Skeleton

**Files to create:**
- `pyproject.toml`
- `src/memkernel/__init__.py` (just `__version__ = "0.1.0"`)
- `src/memkernel/py.typed` (PEP 561 marker, empty)
- `tests/__init__.py`, `tests/unit/__init__.py`, `tests/integration/__init__.py`, `tests/e2e/__init__.py`
- `tests/conftest.py` (register pytest markers, shared fixtures placeholder)
- `eval/.gitkeep`

**pyproject.toml key decisions:**
- `python = ">=3.11,<3.14"`, Poetry build system (cap temporary — torch ≤2.7.1 CVE; lift when PyTorch ships 3.14 wheels for a patched version)
- Runtime: `mcp = ">=1.25,<2"`, `chromadb = ">=1.0,<2"`, `sentence-transformers = ">=4.0,<6"`, `rank-bm25 = ">=0.2"`, `pydantic = ">=2.0,<3"`, `pydantic-settings = ">=2.0,<3"`
- Dev: `pytest = ">=8"`, `pytest-asyncio = ">=0.24"`, `pytest-cov = ">=5"`, `ruff = ">=0.9"`, `mypy = ">=1.13"`
- Tool config: ruff (target py311, line-length 120), mypy strict with pydantic plugin, pytest markers (unit/integration/e2e/slow), asyncio_mode = "auto"
- Package: `packages = [{include = "memkernel", from = "src"}]`
- Script: `memkernel = "memkernel.mcp.server:main"`

**Verify:** `poetry install` → `poetry run pytest -q` (0 tests) → `ruff check . && mypy src/` clean

---

## Step 1: Core Domain Models + Protocols + Config

**Files:** `src/memkernel/core/__init__.py`, `src/memkernel/core/models.py`, `src/memkernel/core/ports.py`, `src/memkernel/config.py`

### config.py — `MemKernelSettings(BaseSettings)`
```
env_prefix = "MEMKERNEL_"
project_id: str = "default"
default_session_id: str = "default"
chroma_persist_path: str = ".memkernel/chroma"
chroma_collection_prefix: str = "memkernel"
embedding_model: str = "all-MiniLM-L6-v2"
embedding_dimension: int = 384
search_top_k: int = 5
rrf_k: int = 60
preview_length: int = 200
episode_ttl_days: int = 30
transport: Literal["stdio", "streamable-http"] = "stdio"
host: str = "127.0.0.1"
port: int = 8765
```

### core/models.py
- `MemoryType(str, Enum)`: decision, convention, code, episode
- `Memory(BaseModel)`: ref_id, content, type, project_id, session_id, timestamp (UTC datetime), source, content_hash, token_count, checkpoint (bool)
- `ArtifactRef(BaseModel)`: ref_id, preview, score, token_count, type, timestamp (matches spec FR-003 — no checkpoint field; checkpoint filtering is query-side via `checkpoint_only` param)
- `SearchResult(BaseModel)`: ref_id, score, rank (internal, pre-fusion)
- `SearchQuery(BaseModel)`: query_text, type_filter, session_id_filter, checkpoint_only, top_k

### core/ports.py — Protocol definitions (architectural keystone)

**VectorStorePort:**
- `upsert(ref_id, content, embedding, metadata) -> None`
- `search_dense(query_embedding, top_k, where?) -> list[SearchResult]`
- `get_by_id(ref_id) -> Memory | None`
- `delete(ref_id) -> bool`
- `list_all(where?) -> list[Memory]` — for BM25 rebuild
- `find_by_hash(content_hash, type) -> Memory | None` — for dedup (scoped to content_hash + type)
- `update_metadata(ref_id, metadata) -> None` — for dedup metadata refresh
- `count() -> int`

**EmbeddingPort:**
- `embed(texts: list[str]) -> list[list[float]]`
- `dimension -> int` (property)

**SparseIndexPort:**
- `add(ref_id, content) -> None`
- `remove(ref_id) -> None`
- `search(query, top_k) -> list[SearchResult]` — returns top_k results (for unfiltered use)
- `search_all(query) -> list[SearchResult]` — scores entire corpus, returns all results with score > 0 (for filtered use — caller applies metadata filters then truncates)
- `rebuild(documents: list[tuple[str, str]]) -> None`
- `needs_rebuild: bool` — read-only property; `True` after an add/remove failure, cleared by `rebuild()`
- `mark_needs_rebuild() -> None` — sets the flag; called by the service layer after catching an add/remove exception
- `__len__() -> int`

**ChunkerPort** (stub for future US3):
- `chunk(content, metadata) -> list[str]`

**Verify:** `mypy src/` strict passes, `ruff check .` clean

---

## Step 2: ChromaDB Storage Adapter (parallel with 3, 4)

**Files:** `src/memkernel/storage/__init__.py`, `src/memkernel/storage/chroma.py`, `tests/unit/test_chroma.py`, `tests/integration/test_chroma_integration.py`

**`ChromaVectorStore` implements `VectorStorePort`:**
- Constructor: takes `MemKernelSettings`, creates ChromaDB client + collection (`{prefix}_{project_id}`). Uses `embedding_function=None` — we manage embeddings ourselves.
- Metadata serialization: datetime → ISO string, MemoryType → string value, checkpoint → bool. Helper functions `_to_chroma_metadata` / `_from_chroma_metadata`.
- `search_dense`: converts ChromaDB distances to scores (`1.0 / (1.0 + distance)` for L2, or `1.0 - distance` for cosine). Returns `SearchResult` objects.
- `find_by_hash`: uses ChromaDB `where={"$and": [{"hash": content_hash}, {"type": type_value}]}` filter (dedup scoped to content + type).
- `update_metadata`: **fetch-and-merge semantics**. Reads existing metadata via `collection.get(ids=[ref_id])`, merges only the caller-specified keys into the existing dict, then calls `collection.update(ids=[ref_id], metadatas=[merged])`. This preserves immutable fields (`project_id`, `hash`, `token_count`, `source`, `type`) while allowing callers to update only mutable fields (`session_id`, `timestamp`, `checkpoint`). The method signature takes `ref_id` and a partial `metadata` dict — it MUST NOT replace the full metadata blob.

**Tests:** Unit tests use in-memory ChromaDB client. Integration tests use PersistentClient with tmp_path, marked `@pytest.mark.integration`. **Specific test for update_metadata**: verify that after calling `update_metadata` with `{"session_id": "new"}`, all other metadata fields (`project_id`, `hash`, `token_count`, `source`, `type`) remain unchanged.

---

## Step 3: Embedding Adapter (parallel with 2, 4)

**Files:** `src/memkernel/retrieval/__init__.py`, `src/memkernel/retrieval/embeddings.py`, `tests/unit/test_embeddings.py`

**`SentenceTransformerEmbedding` implements `EmbeddingPort`:**
- Lazy import of `sentence_transformers` in `__init__`
- Model loaded once, reused for all calls
- `embed` accepts batch, returns `list[list[float]]`

**Also create `MockEmbedding` in `tests/conftest.py`** — deterministic fake embeddings (hash-based, small dimension=8) for use in all unit tests.

**Tests:** Marked `@pytest.mark.slow` (model download). Verify dimension=384, determinism, batch correctness.

---

## Step 4: BM25 Side Index (parallel with 2, 3)

**Files:** `src/memkernel/retrieval/sparse.py`, `tests/unit/test_sparse.py`

**`BM25Index` implements `SparseIndexPort`:**
- `rank_bm25.BM25Okapi` is immutable — maintain `dict[str, list[str]]` (ref_id → tokens) and rebuild BM25Okapi on demand via dirty flag
- `_ensure_index()` called before search — only rebuilds if dirty
- `_tokenize(text)`: whitespace + lowercase for MVP
- `rebuild(documents)`: bulk load from (ref_id, content) pairs, called on server startup
- `_needs_rebuild` flag: set to `True` after any add/remove failure. On next `search()`, triggers full rebuild from authoritative store before returning results (see Step 6 for wiring)
- `search_all(query) -> list[SearchResult]`: scores the **entire corpus** via `get_scores()` and returns all results with score > 0, sorted descending. This is the primary search method — the caller applies metadata filters and top_k cutoff. `get_scores()` is O(n) over the corpus which is fine for MVP scale (hundreds to low thousands).

**Tests:** add+search, remove+search, rebuild, empty index, scoring order, `_needs_rebuild` flag triggers rebuild on next search.

---

## Step 5: Hybrid Search Engine (depends on 2, 3, 4)

**Files:** `src/memkernel/retrieval/search.py`, `tests/unit/test_search.py`

**`HybridSearchService`:**
- Constructor: takes VectorStorePort, EmbeddingPort, SparseIndexPort, MemKernelSettings
- `search(SearchQuery) -> list[ArtifactRef]`:
  1. Build ChromaDB `where` filter from query filters
  2. Embed query text
  3. Dense search via vector store (over-fetch: top_k × 3, filters applied natively by ChromaDB)
  4. Sparse search via BM25: call `search_all(query)` to get **all** scored results from the full corpus, then filter by metadata (fetch via `get_by_id` for each hit), then take top_k × 3. This avoids the cutoff problem — filtering happens on the full scored list, not a pre-truncated one.
  5. RRF fusion: `score(d) = Σ 1/(k + rank_i(d))`, k=60 configurable
  6. Take top_k, build ArtifactRefs from vector store lookups
- Stale BM25 entries (get_by_id → None) skipped silently
- **Optimization note**: For unfiltered queries, `search_all` + filter is equivalent to the old approach but without a blind cutoff. For filtered queries, this ensures no valid sparse matches are missed. At MVP scale (< 5K docs), scoring the full corpus + N get_by_id calls is negligible.

**Tests:** RRF fusion math, where filter construction, stale entry handling, filtered sparse search correctness (verify valid results below old cutoff are found), end-to-end with mocked ports.

---

## Step 6: Memory Service + Types + Lifecycle + Dedup (depends on 1–5)

**Files:** `src/memkernel/core/services.py`, `src/memkernel/memory/__init__.py`, `src/memkernel/memory/types.py`, `src/memkernel/memory/lifecycle.py`, `src/memkernel/memory/dedup.py`, `tests/unit/test_services.py`, `tests/unit/test_dedup.py`

### memory/dedup.py
- `compute_content_hash(content: str) -> str` — SHA-256 hex digest

### memory/types.py
- TTL policies: decision/convention/code → None (no expiry), episode → configurable days
- `get_ttl_days(memory_type, settings) -> int | None`

### memory/lifecycle.py
- `is_expired(memory, settings) -> bool` — passive TTL check (no proactive eviction in MVP)

### core/services.py — `MemoryService`

**`retain(content, type, session_id?, checkpoint?, source?) -> ref_id`:**
1. Compute content_hash
2. Dedup check: `find_by_hash(content_hash, type)` → scoped to content + type pair. If exists, update mutable metadata (`session_id`, `timestamp`, `checkpoint`) via `update_metadata`, return existing ref_id. No re-embedding. Same content with a different `type` creates a new memory (separate ref_id). This extends ADR-5: the dedup key is `(content_hash, type)` not just `content_hash`.
3. New memory: generate UUID, embed content, write to ChromaDB first (authoritative), then add to BM25. If BM25 add fails: log error AND call `sparse_index.mark_needs_rebuild()` so the next search triggers a full rebuild from ChromaDB before returning results.

**`recall(query, type?, session_id?, checkpoint_only?, top_k?) -> list[ArtifactRef]`:**
- If `sparse_index.needs_rebuild`, call `rebuild_sparse_index()` first (self-healing before search)
- Delegate to HybridSearchService, filter expired results post-search

**`get(ref_id) -> Memory | None`:** Direct vector store lookup
**`forget(ref_id) -> bool`:** Delete from ChromaDB first, then BM25. If BM25 remove fails: log error AND call `sparse_index.mark_needs_rebuild()`.
**`rebuild_sparse_index()`:** Load all from ChromaDB, call `sparse_index.rebuild(...)`. Clears `_needs_rebuild` flag. Called on server startup and auto-triggered before search when flag is set.

Token estimation: `len(text) // 4` (MVP heuristic)

**Tests:** Mocked ports — retain new, retain dedup, recall with filters, forget both stores, BM25 failure handling.

---

## Step 7: MCP Server + Tools (depends on 6)

**Files:** `src/memkernel/mcp/__init__.py`, `src/memkernel/mcp/server.py`, `src/memkernel/mcp/tools/__init__.py`, `src/memkernel/mcp/tools/memory.py`, `tests/e2e/test_mcp_roundtrip.py`

### MCP SDK patterns (verified against `mcp>=1.25`):
- `from mcp.server.fastmcp import FastMCP, Context`
- Lifespan: `@asynccontextmanager async def lifespan(server: FastMCP) -> AsyncIterator[AppContext]`
- Constructor: `FastMCP("Name", host=..., port=..., lifespan=...)` — host/port configured here, not on `run()`
- Tools: `@server.tool()` decorator (parentheses required), `Context` param auto-injected and excluded from schema
- Resources: `@server.resource("memory://status")`
- Run: `server.run(transport="stdio")` or `server.run(transport="streamable-http")` — transport only, no host/port args
- Context access: `ctx.request_context.lifespan_context.memory_service`
- **Do NOT give `ctx` a default value** — SDK injects it automatically

### mcp/server.py — single settings source
```python
@dataclass
class MemKernelContext:
    memory_service: MemoryService
    settings: MemKernelSettings

def create_server(settings: MemKernelSettings | None = None) -> FastMCP:
    """Factory — single source of truth for settings.

    The lifespan closure captures `settings` from here.
    Tests pass custom settings (e.g. port=0, in-memory chroma);
    production calls with None to load from env.
    """
    settings = settings or MemKernelSettings()

    @asynccontextmanager
    async def lifespan(server: FastMCP) -> AsyncIterator[MemKernelContext]:
        # uses `settings` from enclosing scope — same instance as server config
        # init embedding, chroma, bm25, search service, memory service
        # rebuild BM25 from ChromaDB
        yield MemKernelContext(memory_service=..., settings=settings)

    server = FastMCP(
        "MemKernel",
        host=settings.host,       # used by streamable-http transport
        port=settings.port,       # used by streamable-http transport
        lifespan=lifespan,
    )
    register_memory_tools(server)   # from mcp/tools/memory.py
    register_health_resource(server) # from mcp/server.py (below)
    return server
```

**Key invariant**: `settings` is created once in `create_server()` and shared via closure into the lifespan. The lifespan never constructs its own `MemKernelSettings()`. This guarantees the server transport config (host/port) and runtime components (project_id, persist_path, embedding model) always use the same instance. Tests call `create_server(test_settings)` with overrides; production calls `create_server()` which loads from env.

### mcp/tools/memory.py — explicit registration

Tools are registered via a `register_memory_tools(server: FastMCP)` function, not module-level decorators. This is required because the `FastMCP` instance is factory-created:

```python
def register_memory_tools(server: FastMCP) -> None:
    @server.tool()
    async def retain(content: str, type: str, ..., ctx: Context) -> dict: ...

    @server.tool()
    async def recall(query: str, ..., ctx: Context) -> list[dict]: ...

    @server.tool()
    async def get(ref_id: str, ctx: Context) -> dict: ...

    @server.tool()
    async def forget(ref_id: str, ctx: Context) -> dict: ...
```

4 tools total:
- `retain(content, type, session_id="default", checkpoint=False, source="")` → `{"ref_id": ...}`
- `recall(query, type?, session_id?, checkpoint_only=False, top_k=5)` → list of ArtifactRef dicts
- `get(ref_id)` → full Memory dict or `{"error": "not_found"}`
- `forget(ref_id)` → `{"ref_id": ..., "deleted": bool}`

### Health resource — same registration pattern
```python
def register_health_resource(server: FastMCP) -> None:
    @server.resource("memory://status")
    async def status(ctx: Context) -> str:
        app_ctx = ctx.request_context.lifespan_context
        ...
```

### Entry point
- `main()` calls `create_server()` (loads settings from env), then `server.run(transport=server_settings.transport)`:
  - **stdio**: `server.run(transport="stdio")` — ignores host/port, communicates over stdin/stdout
  - **streamable-http**: `server.run(transport="streamable-http")` — binds to host:port already on the FastMCP instance
- pyproject.toml script: `memkernel = "memkernel.mcp.server:main"`
- Transport selection via env var: `MEMKERNEL_TRANSPORT=streamable-http` or `MEMKERNEL_TRANSPORT=stdio` (default)
- Tests: `create_server(test_settings)` with `port=0` for free port binding, in-memory chroma path, etc.

**Important:** For stdio transport, never write to stdout (breaks JSON-RPC). Configure Python logging to stderr for both transports.

### E2E tests
Two E2E test paths, both marked `@pytest.mark.e2e` and `@pytest.mark.slow`:
1. **stdio round-trip**: MCP SDK in-process client → retain → recall (verify ArtifactRef) → get (verify full content) → forget → recall (verify empty)
2. **HTTP round-trip**: Start server on `127.0.0.1` with a free port (use `port=0` or a pytest fixture), connect via MCP StreamableHTTP client, run the same retain → recall → get → forget sequence. This verifies FR-001's Streamable HTTP requirement.

---

## Build Order (dependency graph)

```
Step 0: Bootstrap
  │
  v
Step 1: Models + Ports + Config
  │
  ├──────────┼──────────┐
  v          v          v
Step 2     Step 3     Step 4     ← parallel
(Chroma)   (Embed)    (BM25)
  │          │          │
  └──────────┼──────────┘
             v
           Step 5: Hybrid Search
             │
             v
           Step 6: Memory Service
             │
             v
           Step 7: MCP Server + E2E
```

---

## Verification (Checkpoint US1+US2 from tasks.md)

After all steps complete, verify:
- [ ] `poetry install` succeeds
- [ ] `poetry run ruff check . && poetry run mypy src/` — zero errors
- [ ] `poetry run pytest -m unit --tb=short -q` — all unit tests pass
- [ ] `poetry run pytest -m integration --tb=short -q` — ChromaDB integration tests pass
- [ ] `poetry run pytest -m e2e --tb=short -q` — MCP round-trip works (both stdio and streamable-http)
- [ ] MCP client can retain with type + session_id, recall by query, get full content, forget
- [ ] `recall` returns ArtifactRef (ref_id, preview, score, token_count, type, timestamp — not full content)
- [ ] `recall` with type filter returns only matching MemoryType
- [ ] `recall` with session_id filter returns only matching session
- [ ] Content dedup: same content + same type twice → same ref_id, updated session_id + timestamp + checkpoint
- [ ] Content dedup: same content + different type → different ref_id (separate memories)
- [ ] `forget` removes from both ChromaDB and BM25
- [ ] BM25 failure during retain/forget sets `_needs_rebuild`; next recall triggers rebuild before search
- [ ] `recall` returns ArtifactRef matching spec FR-003 shape (no `checkpoint` field in response)
- [ ] Filtered sparse search: with session_id filter, valid BM25 matches are not missed due to cutoff
- [ ] Total tool count = 4 (< 10 target)

---

## Files created/modified (complete list)

```
pyproject.toml                              ← NEW
src/memkernel/__init__.py                   ← NEW
src/memkernel/py.typed                      ← NEW
src/memkernel/config.py                     ← NEW
src/memkernel/core/__init__.py              ← NEW
src/memkernel/core/models.py                ← NEW
src/memkernel/core/ports.py                 ← NEW
src/memkernel/core/services.py              ← NEW
src/memkernel/storage/__init__.py           ← NEW
src/memkernel/storage/chroma.py             ← NEW
src/memkernel/retrieval/__init__.py         ← NEW
src/memkernel/retrieval/embeddings.py       ← NEW
src/memkernel/retrieval/sparse.py           ← NEW
src/memkernel/retrieval/search.py           ← NEW
src/memkernel/memory/__init__.py            ← NEW
src/memkernel/memory/types.py               ← NEW
src/memkernel/memory/lifecycle.py           ← NEW
src/memkernel/memory/dedup.py               ← NEW
src/memkernel/mcp/__init__.py               ← NEW
src/memkernel/mcp/server.py                 ← NEW
src/memkernel/mcp/tools/__init__.py         ← NEW
src/memkernel/mcp/tools/memory.py           ← NEW
tests/__init__.py                           ← NEW
tests/conftest.py                           ← NEW (MockEmbedding, fixtures)
tests/unit/__init__.py                      ← NEW
tests/unit/test_chroma.py                   ← NEW
tests/unit/test_embeddings.py               ← NEW
tests/unit/test_sparse.py                   ← NEW
tests/unit/test_search.py                   ← NEW
tests/unit/test_services.py                 ← NEW
tests/unit/test_dedup.py                    ← NEW
tests/integration/__init__.py               ← NEW
tests/integration/test_chroma_integration.py ← NEW
tests/e2e/__init__.py                       ← NEW
tests/e2e/test_mcp_roundtrip.py             ← NEW
eval/.gitkeep                               ← NEW
```

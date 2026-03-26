# MemKernel

Code-aware memory server for AI coding copilots.

MemKernel gives Claude Code (and any MCP-compatible copilot) persistent memory across sessions. When Claude compacts context or a session ends, project decisions, conventions, and code understanding are normally lost. MemKernel stores them in a local vector database and retrieves them on demand.

**Key differentiator**: MemKernel understands code as code. It uses tree-sitter AST parsing to chunk files at function and class boundaries, embeds chunks with scope context, and provides hybrid search (dense + BM25) for both semantic queries and exact identifier lookup.

---

## Requirements

- Python 3.11 – 3.13
- [Poetry](https://python-poetry.org) (for development installs)

---

## Install

```bash
pip install memkernel
```

Or with Poetry:

```bash
poetry add memkernel
```

---

## Add to Claude Code

### 1. Register the MCP server

Add MemKernel to `.claude/settings.json` in your project:

```json
{
  "mcpServers": {
    "memkernel": {
      "command": "memkernel",
      "args": [],
      "env": {
        "MEMKERNEL_PROJECT_ID": "my-project"
      }
    }
  }
}
```

Replace `my-project` with a short identifier for the project — memories are isolated per project.

### 2. Add memory instructions to CLAUDE.md

Copy the contents of [`templates/claude-memory-instructions.md`](templates/claude-memory-instructions.md) into your project's `CLAUDE.md`. This tells Claude when and how to call the memory tools.

### 3. (Optional) Install compaction hooks

Copy the hook scripts from [`templates/hooks/`](templates/hooks/) to `.claude/hooks/` and register them in `.claude/settings.json` to automate checkpoint saves before compaction and context recovery after. See the Prerequisites section inside each script for the Python environment requirement.

---

## MCP Tools

| Tool | What it does |
|------|-------------|
| `retain(content, type, ...)` | Store a memory. Returns `ref_id`. Idempotent — identical content + type returns the same `ref_id`. |
| `recall(query, ...)` | Search by natural language or identifier. Returns lightweight `ArtifactRef` list. |
| `get(ref_id)` | Fetch full content of a specific memory. |
| `forget(ref_id)` | Delete a memory from all indexes. |

### Memory types

| Type | Use for | Expiry |
|------|---------|--------|
| `decision` | Architecture choices, library selections | Never |
| `convention` | Naming rules, code style, project patterns | Never |
| `code` | Function/class snapshots, API contracts | Never |
| `episode` | Session events, compaction checkpoints | 30 days (configurable) |

### Quick examples

```
retain(
  content="We chose PostgreSQL over SQLite because the team needs concurrent writes",
  type="decision",
  session_id="session-2024-06-01"
)

recall(query="database choice", top_k=5)

recall(query="session checkpoint", checkpoint_only=True)

get(ref_id="<ref_id from recall>")

forget(ref_id="<ref_id>")
```

---

## Configuration

All settings are read from environment variables with the `MEMKERNEL_` prefix, or from a `.env` file.

| Variable | Default | Description |
|----------|---------|-------------|
| `MEMKERNEL_PROJECT_ID` | `default` | Project namespace — memories are isolated per project |
| `MEMKERNEL_DEFAULT_SESSION_ID` | `default` | Session tag applied when `session_id` is omitted from `retain` |
| `MEMKERNEL_CHROMA_PERSIST_PATH` | `.memkernel/chroma` | ChromaDB data directory. Empty string = in-memory (ephemeral) |
| `MEMKERNEL_CHROMA_COLLECTION_PREFIX` | `memkernel` | Prefix for ChromaDB collection names (`{prefix}_{project_id}`) |
| `MEMKERNEL_EMBEDDING_MODEL` | `all-MiniLM-L6-v2` | Sentence-transformers model name |
| `MEMKERNEL_EMBEDDING_DIMENSION` | `384` | Output dimension of the embedding model |
| `MEMKERNEL_SEARCH_TOP_K` | `5` | Default number of results returned by `recall` |
| `MEMKERNEL_RRF_K` | `60` | Reciprocal rank fusion constant (higher = flatter score distribution) |
| `MEMKERNEL_PREVIEW_LENGTH` | `200` | Max characters in the `preview` field of `ArtifactRef` |
| `MEMKERNEL_CHUNK_SIZE` | `1500` | Max characters per AST chunk (code memories) |
| `MEMKERNEL_CHUNK_OVERLAP` | `200` | Character overlap between token-based fallback chunks |
| `MEMKERNEL_EPISODE_TTL_DAYS` | `30` | Days before episode memories expire |
| `MEMKERNEL_TRANSPORT` | `stdio` | `stdio` or `streamable-http` |
| `MEMKERNEL_HOST` | `127.0.0.1` | Host for `streamable-http` transport |
| `MEMKERNEL_PORT` | `8765` | Port for `streamable-http` transport |

---

## Transports

### stdio (default)

Used by Claude Code and most MCP clients. The client spawns the server as a subprocess.

```bash
memkernel           # stdio, uses defaults
```

### Streamable HTTP

For persistent server processes or multi-client setups:

```bash
MEMKERNEL_TRANSPORT=streamable-http memkernel
```

The server listens at `http://127.0.0.1:8765/mcp` by default.

---

## Admin API

A FastAPI admin server provides health and stats endpoints (independent of MCP):

```bash
uvicorn memkernel.api.app:app --host 127.0.0.1 --port 8766
```

| Endpoint | Description |
|----------|-------------|
| `GET /health` | Server health and memory count |
| `GET /stats` | Total memory count, per-type breakdown, growth rate, last recall latency |
| `GET /collections` | List ChromaDB collections |

---

## Development

```bash
git clone https://github.com/gosha70/memkernel
cd memkernel
poetry install
poetry run pytest --tb=short -q          # full test suite
poetry run pytest -m "not slow" -q       # skip slow tests
ruff check . && mypy src/                # lint + type check
```

CI runs on every push and PR: lint, type check, tests (≥ 80% coverage), security scan, and build verification.

---

## Architecture

```
src/memkernel/
├── mcp/           # MCP server + tool definitions (retain, recall, get, forget)
├── core/          # Domain logic + ports (interfaces)
├── storage/       # ChromaDB adapter
├── retrieval/     # AST chunking, embeddings, hybrid search (dense + BM25 + RRF)
├── memory/        # TTL policies, deduplication
├── api/           # FastAPI admin endpoints
└── config.py      # Pydantic settings
```

Ports-and-adapters design: `core/` depends only on protocols in `core/ports.py`, never on concrete backends. Storage and embedding backends are swappable.

---

## License

MIT

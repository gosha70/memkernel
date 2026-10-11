# MemKernel

Code-aware memory server for AI coding copilots.

MemKernel gives Claude Code (and any MCP-compatible copilot) persistent memory across sessions. When Claude compacts context or a session ends, project decisions, conventions, and code understanding are normally lost. MemKernel stores them in a local vector database and retrieves them on demand.

**Key differentiator**: MemKernel understands code as code. It uses tree-sitter AST parsing to chunk files at function and class boundaries, embeds chunks with scope context, and provides hybrid search (dense + BM25) for both semantic queries and exact identifier lookup.

**Tiered memory (0.2)**: memories live in three tiers with different persistence rules — *working* (the current task, hours), *short-term* (episodes and observations, decays unless recalled) and *long-term* (decisions, conventions, facts, procedures, code; never decays, replaced by supersession). Recall ranks by relevance, recency and importance; `consolidate` and `promote` move what proved useful into long-term memory; an LLM-wiki bridge keeps a human-readable, git-versioned copy of long-term knowledge. Design: [`docs/architecture/memory-tiers.md`](docs/architecture/memory-tiers.md).

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

### 3. (Optional) Install lifecycle hooks

Copy the hook scripts from [`templates/hooks/`](templates/hooks/) to `.claude/hooks/` and register them in `.claude/settings.json`:

| Hook | Claude Code event | What it does |
|------|-------------------|--------------|
| `session-start.py` | `SessionStart` | Consolidates, recovers the latest checkpoint and long-term context, lists promotion candidates |
| `pre-compact.py` | `PreCompact` | Retains a checkpoint episode, runs a consolidation pass |
| `post-compact.py` | `PostCompact` | Re-injects the checkpoint, long-term context and promotion candidates |

See the Prerequisites section inside each script for the Python environment requirement.

---

## MCP Tools

| Tool | What it does |
|------|-------------|
| `retain(content, type, session_id?, checkpoint?, source?, importance?, tags?, supersedes?)` | Store a memory. Returns `ref_id`. Idempotent — identical content + type returns the same `ref_id`. `supersedes` hides the memory it replaces. |
| `recall(query, type?, tier?, session_id?, checkpoint_only?, top_k?)` | Search by natural language or identifier. Returns lightweight `ArtifactRef` list ranked by relevance + recency + importance. Records an access (reinforces retention). |
| `get(ref_id)` | Fetch full content of a specific memory. Records an access. |
| `forget(ref_id)` | Delete a memory from all indexes. |
| `promote(ref_id, type, content?, importance?, tags?)` | Turn a short-term/working memory into a long-term one (you supply the distilled text). Keeps provenance via `promoted_from`. |
| `consolidate(session_id?, limit?)` | Purge expired short-term memories and list the ones most worth promoting (ranked by importance × how often they were recalled). |
| `forget_expired()` | Delete every short-term/working memory whose retention window lapsed. |
| `wiki_export(wiki_dir?)` | Compile long-term memories without a wiki page into draft markdown pages (`index.md`, `log.md` updated). |
| `wiki_import(wiki_dir?)` | Index curated wiki pages as long-term memories (idempotent; changed pages supersede). |

### Memory types and tiers

| Type | Tier | Use for | Default importance | Expiry |
|------|------|---------|--------------------|--------|
| `decision` | long-term | Architecture choices, library selections | 0.9 | Never (supersede instead) |
| `convention` | long-term | Naming rules, code style, project patterns | 0.9 | Never |
| `fact` | long-term | Durable project facts: build commands, environments, contracts | 0.7 | Never |
| `procedure` | long-term | How-to that worked: workflows, recipes, verified skills | 0.8 | Never |
| `code` | long-term | Function/class snapshots, API contracts | 0.6 | Never |
| `episode` | short-term | Session events, compaction checkpoints | 0.4 | 30 days, extended by every recall |
| `observation` | short-term | Findings, tool outputs, things noticed | 0.3 | 7 days, extended by every recall |
| `task` | working | The current goal, plan state, open questions | 0.5 | 24 hours |

Retention: `ttl = base_ttl × (1 + access_boost × access_count)`, measured from the later of creation and last access. Long-term memories never expire; a newer memory that `supersedes` an older one hides it from recall.

### Session protocol

1. **Session start** — `recall(tier="long_term", query=<task>)`, plus the latest checkpoint (`checkpoint_only=true`). The `session-start.py` hook does this and prints promotion candidates.
2. **While working** — `retain(type="task")` when the plan changes; `retain(type="observation")` for findings; durable knowledge as `decision` / `convention` / `fact` / `procedure`.
3. **Before compaction** — `retain(type="episode", checkpoint=true)` (the `pre-compact.py` hook) and `consolidate()`.
4. **After compaction / end of phase** — `promote(ref_id, type, content)` for the candidates worth keeping.
5. **Curate** — `wiki_export` → review the drafts → `wiki_import`.

### Quick examples

```
retain(
  content="We chose PostgreSQL over SQLite because the team needs concurrent writes",
  type="decision",
  session_id="session-2024-06-01"
)

recall(query="database choice", top_k=5)

recall(query="session checkpoint", checkpoint_only=True)

retain(content="pytest hangs unless MEMKERNEL_PROJECT_ID is set", type="observation", tags=["ci"])

consolidate()                      # -> {"purged": 0, "candidates": [{"ref_id": ..., "access_count": 3, ...}]}

promote(ref_id="<candidate>", type="fact", content="CI must export MEMKERNEL_PROJECT_ID before pytest.")

retain(content="Use arq, not Celery", type="decision", supersedes="<old decision ref_id>")

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
| `MEMKERNEL_EPISODE_TTL_DAYS` | `30` | Base TTL for `episode` memories (short-term) |
| `MEMKERNEL_OBSERVATION_TTL_DAYS` | `7` | Base TTL for `observation` memories (short-term) |
| `MEMKERNEL_TASK_TTL_HOURS` | `24` | Base TTL for `task` memories (working) |
| `MEMKERNEL_ACCESS_BOOST` | `0.5` | Each recall extends a short-term memory's TTL by this fraction of its base TTL |
| `MEMKERNEL_RECENCY_HALF_LIFE_DAYS` | `7.0` | Recency decay half-life used in recall scoring (short-term tier) |
| `MEMKERNEL_RECALL_WEIGHT_RELEVANCE` | `1.0` | Weight of hybrid-search relevance in the final recall score |
| `MEMKERNEL_RECALL_WEIGHT_RECENCY` | `0.3` | Weight of recency in the final recall score |
| `MEMKERNEL_RECALL_WEIGHT_IMPORTANCE` | `0.3` | Weight of importance in the final recall score |
| `MEMKERNEL_WIKI_DIR` | `` | Directory of the LLM wiki used by `wiki_export` / `wiki_import` (empty = pass `wiki_dir` explicitly) |
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

## Embedding MemKernel in your own harness

```python
from memkernel.factory import build_service
from memkernel.core.models import MemoryType

svc = build_service()                      # settings from MEMKERNEL_* env vars
svc.retain("Use Postgres", MemoryType.DECISION)
for ref in svc.recall("database"):
    print(ref.tier, ref.score, ref.preview)
report = svc.consolidate()                 # {"purged": n, "candidates": [...]}
```

`build_service()` is the supported entry point; the MCP server, the admin API and the hook templates all use it. Integration notes for `code-copilot-team` and `haa` are in [`docs/integration/harness-integration.md`](docs/integration/harness-integration.md).

## LLM wiki bridge

Long-term memory has a human-readable twin: a markdown wiki in the [LLM Wiki](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) pattern (`index.md`, `log.md`, typed pages with cited sources — the same schema as `code-copilot-team/knowledge/wiki`).

- `wiki_export` compiles every long-term memory that has no page yet into a **draft** page under `decisions/`, `concepts/` or `workflows/`, with the required sections and a `memkernel://<project>/<ref_id>` citation. Existing pages are never overwritten.
- `wiki_import` indexes curated pages as long-term memories so `recall` finds the reviewed version; a changed page supersedes its earlier memory.

Set `MEMKERNEL_WIKI_DIR` (for example `knowledge/wiki`) or pass `wiki_dir` to the tools. Rationale and the proposed standalone `ai-wiki` repo: [`docs/adr/ADR-008-llm-wiki-as-semantic-layer.md`](docs/adr/ADR-008-llm-wiki-as-semantic-layer.md).

## Admin API

A FastAPI admin server provides health and stats endpoints (independent of MCP):

```bash
uvicorn memkernel.api.app:app --host 127.0.0.1 --port 8766
```

| Endpoint | Description |
|----------|-------------|
| `GET /health` | Server health and memory count |
| `GET /stats` | Total memory count, per-type and per-tier breakdown, growth rate, last recall latency |
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
├── mcp/           # MCP server + tool definitions (memory tools, wiki tools)
├── core/          # Domain models (tiers, types), MemoryService, ports (interfaces)
├── storage/       # ChromaDB adapter
├── retrieval/     # AST chunking, embeddings, hybrid search (dense + BM25 + RRF + rescoring)
├── memory/        # Lifecycle: TTL/decay policies, retention, deduplication
├── wiki/          # LLM-wiki bridge: page model, export, import
├── api/           # FastAPI admin endpoints
├── factory.py     # build_service() — the supported embedding entry point
└── config.py      # Pydantic settings
```

Ports-and-adapters design: `core/` depends only on protocols in `core/ports.py`, never on concrete backends. Storage and embedding backends are swappable.

Further reading: [`docs/architecture/memory-tiers.md`](docs/architecture/memory-tiers.md) (design), [`docs/research/memory-literature-review.md`](docs/research/memory-literature-review.md) (HRM, JEPA, MemGPT, Mem0, Zep, HippoRAG, Generative Agents, Titans, …), [`docs/research/sibling-projects.md`](docs/research/sibling-projects.md) (what is shared with rlm-studio, document-assistant, ragkit, code-copilot-team, haa), [`docs/adr/`](docs/adr/), [`docs/roadmap.md`](docs/roadmap.md).

---

## License

MIT

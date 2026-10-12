# MemKernel

[![CI](https://github.com/gosha70/memkernel/actions/workflows/ci.yml/badge.svg)](https://github.com/gosha70/memkernel/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/memkernel)](https://pypi.org/project/memkernel/)
[![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-blue)](pyproject.toml)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-green)](LICENSE)

**Site:** [memkernel.dev](https://memkernel.dev) · **Package:** [pypi.org/project/memkernel](https://pypi.org/project/memkernel/)

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

See the Prerequisites section inside each script for the Python environment requirement. Each script is a thin wrapper over [`MemoryLifecycle`](#embedding-memkernel-in-your-own-harness), so an in-process harness gets the same behaviour without the scripts.

---

## MCP Tools

| Tool | What it does |
|------|-------------|
| `retain(content, type, session_id?, checkpoint?, source?, importance?, tags?, supersedes?)` | Store a memory. Returns `ref_id`. Idempotent — identical content + type returns the same `ref_id`. `supersedes` hides the memory it replaces. |
| `recall(query, type?, tier?, session_id?, checkpoint_only?, top_k?)` | Search by natural language or identifier. Returns lightweight `ArtifactRef` list ranked by relevance + recency + importance. Records an access (reinforces retention). |
| `get(ref_id)` | Fetch full content of a specific memory. Records an access. |
| `forget(ref_id)` | Delete a memory from all indexes. |
| `promote(ref_id, type, content?, importance?, tags?)` | Turn a short-term/working memory into a long-term one (you supply the distilled text). Keeps provenance via `promoted_from`. |
| `consolidate(session_id?, limit?, synthesize?)` | Purge expired short-term memories and list the ones most worth promoting (ranked by importance × how often they were recalled). `synthesize=true` also asks an external reasoner to draft long-term statements (`suggested`). |
| `ask(ref_id, question, mode?)` | Answer a question about one memory without loading it — for a `document` the full body is consulted. `mode`: `direct` \| `rag` \| `rlm` \| `auto`, passed to the reasoner unchanged; the built-in reasoner answers in `rag` mode with the best-matching chunks. Returns `answer`, `mode`, `citations`, `usage`. |
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
| `document` | long-term | Large artefacts (specs, transcripts, files): the body is stored and chunk-indexed, `get` returns a summary, `ask` answers from the indexed chunks (local reasoner) or the body (RLM Studio) | 0.6 | Never |
| `episode` | short-term | Session events, compaction checkpoints | 0.4 | 30 days, extended by every recall |
| `observation` | short-term | Findings, tool outputs, things noticed | 0.3 | 7 days, extended by every recall |
| `task` | working | The current goal, plan state, open questions | 0.5 | 24 hours |

Retention: `ttl = base_ttl × (1 + access_boost × access_count)`, measured from the later of creation and last access. Long-term memories never expire; a newer memory that `supersedes` an older one hides it from recall.

### Session protocol

1. **Session start** — `recall(tier="long_term", query=<task>)`, plus the latest checkpoint (`checkpoint_only=true`). The `session-start.py` hook does this and prints promotion candidates.
2. **While working** — `retain(type="task")` when the plan changes; `retain(type="observation")` for findings; durable knowledge as `decision` / `convention` / `fact` / `procedure`.
3. **Before compaction** — `retain(type="episode", checkpoint=true)` (the `pre-compact.py` hook) and `consolidate()`.
4. **After compaction / end of phase** — `promote(ref_id, type, content)` for the candidates worth keeping.
5. **Large artefacts** — `retain(type="document", content=<body>, source=<name>)` then `ask(ref_id, question)`; never `get` a document to read it.
6. **Curate** — `wiki_export` → review the drafts → `wiki_import`.

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

retain(content=<the whole spec>, type="document", source="specs/auth/spec.md")

ask(ref_id="<document ref_id>", question="Which endpoints need rate limiting?", mode="auto")
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
| `MEMKERNEL_DOCUMENT_STORE` | `local` | Where `document` bodies live (`local` = the project's own ChromaDB collection) |
| `MEMKERNEL_DOCUMENT_SUMMARY_CHARS` | `1000` | Characters of the body kept in a `document` memory's summary record |
| `MEMKERNEL_REASONER` | `local` | `ReasonerPort` behind `ask`: `local` (hybrid search over chunks, no LLM) or `rlmstudio` (falls back to `local` when `rlmstudio` is not importable) |
| `MEMKERNEL_ASK_TOP_K` | `5` | Chunks the local reasoner returns per `ask` |
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

### The session protocol as a component

`MemoryLifecycle` packages what the hook scripts do, so a harness calls four methods instead of re-implementing the protocol. Every method returns markdown ready for injection and does nothing but talk to the service:

```python
from memkernel.factory import build_service
from memkernel.lifecycle import MemoryLifecycle

memory = MemoryLifecycle(build_service())
system_context = memory.on_session_start()       # checkpoint, long-term context, promotion candidates, wiki pointer
...
memory.on_pre_compact(summary)                   # checkpoint episode + consolidation, before the context is compacted
recovered = memory.on_post_compact()             # what to re-inject after compaction
memory.on_session_end(summary)                   # final checkpoint + consolidation
```

### Documents and `ask`

`retain(type="document")` keeps large artefacts out of the context window: the body goes to the document store (built-in: the project's own ChromaDB collection), its chunks are indexed for hybrid search, and the memkernel record is a summary. `ask(ref_id, question, mode)` answers through a `ReasonerPort`:

- `MEMKERNEL_REASONER=local` (default) — no LLM: the question is matched against the document's chunks with dense + BM25 + RRF and the best chunks come back as the answer, `mode="rag"`.
- `MEMKERNEL_REASONER=rlmstudio` — delegates to [rlm-studio](https://github.com/gosha70/rlm-studio)'s `interact(content, question, mode=mode)`, so `direct`, `rag`, `rlm` and `auto` select how the document is read (ADR-009). `rlm-studio` is not a memkernel dependency and is not on PyPI yet; install it from git into the same environment:

  ```bash
  pip install "rlm-studio @ git+https://github.com/gosha70/rlm-studio"
  ```

  When it is not importable, `build_service()` logs a warning and uses the local reasoner. With an external reasoner, `consolidate(synthesize=True)` also drafts long-term statements from the session's short-term memories.

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

### Releasing

Releases are published to PyPI by [`.github/workflows/release.yml`](.github/workflows/release.yml) using trusted publishing (no token in the repo). To cut a release:

1. Set `version` in `pyproject.toml` and move the `[Unreleased]` entries in [`CHANGELOG.md`](CHANGELOG.md) under the new version.
2. Merge to `main` with CI green.
3. Tag and push: `git tag -a v0.3.0 -m "memkernel 0.3.0" && git push origin v0.3.0`.

The workflow refuses a tag that does not match the `pyproject.toml` version, builds the sdist and wheel, smoke-installs the wheel, and uploads through the `pypi` environment.

---

## Architecture

```
src/memkernel/
├── mcp/           # MCP server + tool definitions (memory tools, wiki tools)
├── core/          # Domain models (tiers, types), MemoryService, ports (interfaces)
├── adapters/      # Optional external systems (RLM Studio reasoner), imported lazily
├── storage/       # ChromaDB adapter, local document store
├── retrieval/     # AST/token chunking, embeddings, hybrid search (dense + BM25 + RRF + rescoring), local reasoner
├── memory/        # Lifecycle: TTL/decay policies, retention, deduplication
├── wiki/          # LLM-wiki bridge: page model, export, import
├── api/           # FastAPI admin endpoints
├── factory.py     # build_service() — the supported embedding entry point
├── lifecycle.py   # MemoryLifecycle — the session protocol as a component
└── config.py      # Pydantic settings
```

Ports-and-adapters design: `core/` depends only on protocols in `core/ports.py`, never on concrete backends. Storage and embedding backends are swappable.

Further reading: [`docs/architecture/memory-tiers.md`](docs/architecture/memory-tiers.md) (design), [`docs/research/memory-literature-review.md`](docs/research/memory-literature-review.md) (HRM, JEPA, MemGPT, Mem0, Zep, HippoRAG, Generative Agents, Titans, …), [`docs/research/sibling-projects.md`](docs/research/sibling-projects.md) (what is shared with rlm-studio, document-assistant, ragkit, code-copilot-team, haa), [`docs/adr/`](docs/adr/), [`docs/roadmap.md`](docs/roadmap.md).

---

## Related projects

MemKernel is the memory component of a small family of projects by the same author; each is usable on its own.

| Project | Role | Relationship |
|---|---|---|
| [ai-wiki](https://github.com/gosha70/ai-wiki) | LLM-maintained markdown wiki (ingest / promote / query / lint) | the human-readable form of long-term memory; `wiki_export` / `wiki_import` speak its page schema (ADR-008) |
| [rlm-studio](https://github.com/gosha70/rlm-studio) | Recursive Language Models workbench: Direct / RAG / RLM / auto over large documents | the document layer behind `document` memories and the `ask()` tool (`MEMKERNEL_REASONER=rlmstudio`, ADR-009) |
| [code-copilot-team](https://github.com/gosha70/code-copilot-team) | Enforceable harness configuration for Claude Code, Pi and other copilots | consumes MemKernel through MCP and hooks |
| [haa](https://github.com/gosha70/haa) | Home-built AI coding harness, future component assembler | consumes MemKernel in-process through `build_service()` |

The cross-repository sequence is in [`docs/roadmap.md`](docs/roadmap.md).

## License

Apache-2.0. See [`LICENSE`](LICENSE) and [`NOTICE`](NOTICE). Changes are tracked in [`CHANGELOG.md`](CHANGELOG.md).

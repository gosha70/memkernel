# Sibling projects: what memkernel should take from, give to, or leave alone

Surveyed 2026-10-11 from shallow clones of `gosha70/{rlm-studio, my-llm,
mapatlas, ragkit, document-assistant, code-copilot-team, haa}`. The guiding
principle from the owner: decouple, move each piece to the project where it
belongs, then consume that project as a library.

## Summary table

| Project | Maturity | Relationship to memkernel | Decision |
|---|---|---|---|
| **document-assistant** | high (CI, 36 unit test files, ADRs, eval) | the richest overlapping RAG code (`src/rag/`): BM25 persistence, RRF, cross-encoder reranking, prompt-injection firewall, token-aware splitter, contextual chunk augmentation, embedding provenance in Chroma collection metadata | **extract a shared `ragkit` from `document-assistant/src/rag/`** (langchain-free), not from the existing `ragkit` repo; until then *copy* the small pieces listed below |
| **ragkit** | low / stale (no packaging, import errors, langchain 0.2 pins, no LICENSE file) | an older extraction of the same lineage | **retire** (owner decision): add a LICENSE, archive on GitHub with a pointer, reuse the name for the new extraction |
| **rlm-studio** | high (1.0.0rc1, CI, 80% coverage gate) | the **document layer** (owner decision, ADR-009): hash-deduplicated file store and chunk index behind `StoragePort`; Direct / RAG / RLM / `auto` execution per query; budgets, traces, replay | **optional extra `memkernel[rlm]`**: `document` memory type stored through RLM Studio, `ask(ref_id, question, mode)` tool, reasoner-backed consolidation; memkernel contributes a local embedder shim to RLM Studio's `EmbeddingPort`; also copy `history_context` budgeting helpers and the benchmark/judge scoring pattern |
| **my-llm** | early (Phase A learning lab) | typed-decision models over a Hibernate/Liquibase domain | **nothing to share**; a typed classifier for `MemoryType` at `retain` time is a research idea only |
| **mapatlas** | high (TS monorepo) | geographic field mapping, not a knowledge atlas | **unrelated**; borrow only the dependency-direction lint idea |
| **code-copilot-team (CCT)** | high (v1.1.0, 40+ bash suites) | **already integrates memkernel** (skill, 3 hooks, launcher writes `mcpServers.memkernel`, `setup.sh --memkernel`, Pi MCP backend declaration, dogfood benchmark) and **already hosts an LLM wiki + maintainer** (`knowledge/wiki`, `scripts/wiki_ingest`, 117 tests) | memkernel is the memory backend; CCT's wiki tooling is the candidate for extraction into its own repo (ADR-008) |
| **haa** | work in progress (owner has just started context management) | OpenAI-compatible ReAct loop, Docker sandbox, `harness/memory/agents_md.py`; `chromadb` pinned but unused. **Intended future: a component-assembly harness** where a developer composes memory, sandbox, tools, workflow (later through a UI) | **first non-MCP consumer and the reference assembler**: memkernel must expose itself as composable components (ports, `build_service()`, a `MemoryLifecycle` with `on_session_start / on_pre_compact / on_post_compact / on_session_end`), not just an MCP server |

## What memkernel copies now (each < 120 lines, dependency-light)

From `document-assistant/src/rag/`:

1. `bm25_index.py` `save`/`load` — persist the BM25 index instead of rebuilding
   from Chroma on every start (memkernel rebuilds on start today).
2. `chroma_backend.py` `_PROVENANCE_KEY_*` / `get_embedding_provenance` —
   record the embedding model in collection metadata so a model change is
   detected instead of silently mixing vector spaces.
3. `context_firewall.py` `sanitize_document_text` — recalled memories are
   injected into an agent's context; prompt-injection redaction belongs in
   the server.
4. `reranking.py` `CrossEncoderReranker` — optional second-stage reranker
   behind a port (sentence-transformers is already a dependency).
5. `chunking.py` `get_text_splitter` — token-aware fallback for non-code
   memories (markdown, long episodes); complements `ASTChunker`.

From `rlm-studio/src/rlmstudio/application/services/history_context.py`:

6. `compute_inprompt_budget` + `assemble_inprompt_history_within_budget` —
   pure functions for "how many memories fit in N tokens", used by the
   session-start and post-compaction hooks to size their output.

From `rlm-studio/src/rlmstudio/benchmark/`:

7. The `scoring.py` + `JudgeScorer` pattern for `eval/run_eval.py`, adding
   knowledge-update and abstention categories (see the literature review §4).

## What memkernel gives away

- `retrieval/chunking.py` `ASTChunker` and `retrieval/search.py` `rrf_fuse`
  are the contributions that flow *into* the shared `ragkit` extraction
  (document-assistant has no AST chunking; its RRF is a two-list special
  case of memkernel's n-list version).
- `memkernel.factory.build_service()` is the supported entry point for every
  embedder (CCT hooks, haa). CCT's hooks currently assemble
  `MemoryService` from internals; they should switch to the factory.

## Proposed dependency graph (target state)

```
                    ┌────────────┐      ┌──────────────┐
                    │  ai-wiki   │      │  rlm-studio  │  document layer: file store, chunk index,
                    │ (new repo) │      │ (documents,  │  Direct/RAG/RLM/auto "ask" (ADR-009)
                    └─────▲──────┘      │  reasoning)  │
                          │ [wiki]      └──────▲───────┘
                          │ extra              │ [rlm] extra; memkernel gives back an EmbeddingPort shim
┌───────────┐       ┌─────┴─────────────────────┴──┐     ┌──────────────────────┐
│  ragkit   │──────▶│           memkernel          │◀────│ document-assistant   │ (consumes ragkit; may consume memkernel)
│ (rebuilt  │       │ memories, tiers, recall,     │     └──────────────────────┘
│ from DA)  │       │ consolidation, wiki bridge   │
└───────────┘       └──────────────▲───────────────┘
                                   │ MCP (Claude Code, Pi) / Python components (haa, hooks)
                     ┌─────────────┴─────────────┐
                     │ code-copilot-team    haa  │  haa = component assembler; CCT = rules/workflow supplier
                     └───────────────────────────┘
```

`my-llm` and `mapatlas` stay outside the graph. Licenses: see `docs/licensing.md`.

## Licensing note

Moved to [`../licensing.md`](../licensing.md). Short version: document-assistant
(CC-BY-SA-4.0) must be relicensed before the new `ragkit` is extracted from
it; the old ragkit has no LICENSE file; libraries should converge on
Apache-2.0 (or stay MIT, but not mix in share-alike).

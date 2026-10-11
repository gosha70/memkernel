# Sibling projects: what memkernel should take from, give to, or leave alone

Surveyed 2026-10-11 from shallow clones of `gosha70/{rlm-studio, my-llm,
mapatlas, ragkit, document-assistant, code-copilot-team, haa}`. The guiding
principle from the owner: decouple, move each piece to the project where it
belongs, then consume that project as a library.

## Summary table

| Project | Maturity | Relationship to memkernel | Decision |
|---|---|---|---|
| **document-assistant** | high (CI, 36 unit test files, ADRs, eval) | the richest overlapping RAG code (`src/rag/`): BM25 persistence, RRF, cross-encoder reranking, prompt-injection firewall, token-aware splitter, contextual chunk augmentation, embedding provenance in Chroma collection metadata | **extract a shared `ragkit` from `document-assistant/src/rag/`** (langchain-free), not from the existing `ragkit` repo; until then *copy* the small pieces listed below |
| **ragkit** | low / stale (no packaging, import errors, langchain 0.2 pins) | an older extraction of the same lineage | **treat as dead**; reuse the name for the new extraction |
| **rlm-studio** | high (1.0.0rc1, CI, 80% coverage gate) | different problem (recursive LMs over huge contexts); clean `history_context` budgeting helpers; benchmark/judge scoring pattern; its own docstring plans to adopt a `rag-core` embedder | **no dependency either way**; copy `compute_inprompt_budget`/`assemble_inprompt_history_within_budget` for recall budgeting; later offer memkernel's store/chunker/hybrid search behind rlm-studio's `StoragePort` |
| **my-llm** | early (Phase A learning lab) | typed-decision models over a Hibernate/Liquibase domain | **nothing to share**; a typed classifier for `MemoryType` at `retain` time is a research idea only |
| **mapatlas** | high (TS monorepo) | geographic field mapping, not a knowledge atlas | **unrelated**; borrow only the dependency-direction lint idea |
| **code-copilot-team (CCT)** | high (v1.1.0, 40+ bash suites) | **already integrates memkernel** (skill, 3 hooks, launcher writes `mcpServers.memkernel`, `setup.sh --memkernel`, Pi MCP backend declaration, dogfood benchmark) and **already hosts an LLM wiki + maintainer** (`knowledge/wiki`, `scripts/wiki_ingest`, 117 tests) | memkernel is the memory backend; CCT's wiki tooling is the candidate for extraction into its own repo (ADR-008) |
| **haa** | early scaffold (24 files, no tests) | OpenAI-compatible ReAct loop, Docker sandbox, `harness/memory/agents_md.py` is the whole memory story; `chromadb` pinned but unused | **first non-MCP consumer**: `harness/tools/memory.py` wrapping `memkernel.factory.build_service()` |

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
                    ┌────────────┐
                    │  llm-wiki  │  ← extracted from CCT knowledge/wiki/schema + scripts/wiki_ingest
                    │ (new repo) │
                    └─────▲──────┘
                          │ optional extra
┌───────────┐       ┌─────┴──────┐        ┌──────────────────────┐
│  ragkit   │──────▶│  memkernel │◀───────│ document-assistant   │ (consumes ragkit; may consume memkernel for chat memory)
│ (rebuilt  │       │ (memory    │        └──────────────────────┘
│ from DA)  │       │  server)   │
└───────────┘       └─────▲──────┘
                          │ MCP (Claude Code, Pi) / Python (haa, hooks)
            ┌─────────────┴─────────────┐
            │ code-copilot-team   haa   │
            └───────────────────────────┘
```

`rlm-studio`, `my-llm` and `mapatlas` stay outside the graph.

## Licensing note

`document-assistant` and the old `ragkit` are CC-BY-SA-4.0 (share-alike);
memkernel is MIT; CCT is MIT; haa is Apache-2.0. Anything extracted from
document-assistant into a library that memkernel depends on must be
re-licensed by the owner (MIT or Apache-2.0) before memkernel can depend on
it without inheriting share-alike terms. Copying the small pieces above is
the owner copying their own code and can be relicensed at the same time.

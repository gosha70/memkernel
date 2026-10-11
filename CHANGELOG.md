# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.3.0] - 2026-10-11

### Added

- `document` memory type (long-term, importance 0.6): `retain(type="document")`
  stores the body through a `DocumentStorePort`, indexes its token chunks for
  hybrid search and keeps a summary record; `get` returns the summary, recall
  resolves chunk hits to the document and never lists chunk records (ADR-009).
- `ask(ref_id, question, mode="auto")` MCP tool and `MemoryService.ask`:
  answer a question about one memory without loading it; `mode` is
  `direct | rag | rlm | auto`, passed to the reasoner unchanged.
- Ports `DocumentStorePort` and `ReasonerPort` in `core/ports.py`; `Answer`
  model; built-in `LocalDocumentStore` (ChromaDB) and LLM-free `LocalReasoner`
  (dense + BM25 + RRF over chunks, `mode="rag"`).
- RLM Studio adapter `memkernel.adapters.rlmstudio.RLMStudioReasoner`
  (`MEMKERNEL_REASONER=rlmstudio`, lazy import, falls back to the local
  reasoner with a warning when `rlmstudio` is not installed).
- `consolidate(synthesize=True)`: with an external reasoner, drafts long-term
  statements from the candidates under `"suggested"`.
- `memkernel.lifecycle.MemoryLifecycle` with `on_session_start`,
  `on_pre_compact`, `on_post_compact`, `on_session_end`; the hook templates
  are thin wrappers over it.
- Settings `MEMKERNEL_DOCUMENT_STORE`, `MEMKERNEL_DOCUMENT_SUMMARY_CHARS`,
  `MEMKERNEL_REASONER`, `MEMKERNEL_ASK_TOP_K`; `split_text` / `TokenChunker`
  in `retrieval/chunking.py`.

### Changed

- `consolidate` reports always carry a `suggested` list (empty unless
  `synthesize=True` with an external reasoner).
- `templates/claude-memory-instructions.md` tells the agent to use
  `retain(type="document")` + `ask()` for anything longer than a screen.
- Release workflow uses `actions/upload-artifact@v5` and
  `actions/download-artifact@v6` (Node 24).

### Removed

- The `forget_expired` MCP tool (purging stays inside `consolidate`; the
  `MemoryService.forget_expired` method remains). The server exposes nine
  tools: `retain, recall, get, forget, promote, consolidate, ask, wiki_export,
  wiki_import`.

## [0.2.0] - 2026-10-11

### Added

- Tiered memory model: `working`, `short_term`, `long_term` tiers derived from
  the memory type; new types `fact`, `procedure`, `observation`, `task`
  (ADR-007).
- Per-memory `importance`, `tags`, `access_count`, `last_accessed`,
  `supersedes` and `promoted_from` metadata. Records written by 0.1.x load
  unchanged with derived defaults.
- Recall re-scoring by relevance + recency + importance with configurable
  weights; recency decays from last access; superseded memories are hidden.
- Access-reinforced retention for short-term and working memories
  (`MEMKERNEL_ACCESS_BOOST`, `MEMKERNEL_OBSERVATION_TTL_DAYS`,
  `MEMKERNEL_TASK_TTL_HOURS`, `MEMKERNEL_RECENCY_HALF_LIFE_DAYS`).
- `MemoryService.promote`, `consolidate`, `forget_expired`, `list_memories`.
- MCP tools `promote`, `consolidate`, `forget_expired`, `wiki_export`,
  `wiki_import`; `recall` gains a `tier` filter; `retain` gains `importance`,
  `tags`, `supersedes`.
- LLM-wiki bridge (`memkernel.wiki`): compile long-term memories into draft
  markdown pages and index curated pages as memories (ADR-008);
  `MEMKERNEL_WIKI_DIR` setting.
- `memkernel.factory.build_service()` as the supported Python entry point;
  `templates/hooks/session-start.py`.
- Design docs: architecture, literature review, sibling-project map, ADRs
  007–009, licensing review, roadmap, harness integration plan.
- Release workflow using PyPI trusted publishing.

### Changed

- License changed from MIT to Apache-2.0.
- `recall` and `get` record an access (pass `touch=False` to avoid it).
- `/stats` reports a per-tier breakdown.
- Hook templates build the service through `build_service()` and surface
  promotion candidates after compaction.
- CI frees runner disk before installing dependencies; actions moved to
  `checkout@v5` / `setup-python@v6`.

### Security

- Refreshed `poetry.lock` (130 packages updated): resolves the advisories the
  security scan reported on pyjwt, starlette, urllib3, python-multipart,
  sentence-transformers, transformers, torch, cryptography and others. The
  four chromadb 1.5.9 advisories without a published fix are ignored
  explicitly in CI and must be re-checked on the next chromadb bump.

## [0.1.0] - 2026-03-27

### Added

- Initial release: `retain`, `recall`, `get`, `forget` MCP tools; ChromaDB
  store; sentence-transformers embeddings; BM25 + RRF hybrid search;
  tree-sitter AST chunking; episode TTL; dedup by content hash; FastAPI admin
  API; Claude Code hook templates.

[Unreleased]: https://github.com/gosha70/memkernel/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/gosha70/memkernel/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/gosha70/memkernel/releases/tag/v0.1.0

# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

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

## [0.1.0] - 2026-03-27

### Added

- Initial release: `retain`, `recall`, `get`, `forget` MCP tools; ChromaDB
  store; sentence-transformers embeddings; BM25 + RRF hybrid search;
  tree-sitter AST chunking; episode TTL; dedup by content hash; FastAPI admin
  API; Claude Code hook templates.

[Unreleased]: https://github.com/gosha70/memkernel/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/gosha70/memkernel/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/gosha70/memkernel/releases/tag/v0.1.0

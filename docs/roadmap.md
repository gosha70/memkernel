# Roadmap

Updated 2026-10-11. Ordered by dependency, not by date.

## 0.2 — tiered memory (this branch)

- [x] Working / short-term / long-term tiers; `fact`, `procedure`,
      `observation`, `task` types (ADR-007)
- [x] Access-reinforced retention, recency from last access,
      relevance + recency + importance scoring
- [x] `promote`, `consolidate`, `forget_expired`, `supersedes`
- [x] LLM-wiki bridge: `wiki_export`, `wiki_import` (ADR-008)
- [x] `memkernel.factory.build_service()`; hooks use it; `session-start.py`
- [ ] CHANGELOG, CONTRIBUTING, PyPI publication of `0.2.0`

## 0.3 — hardening with pieces copied from sibling projects

(see `docs/research/sibling-projects.md`)

- [ ] BM25 index persistence (document-assistant `bm25_index.save/load`)
- [ ] Embedding-model provenance in Chroma collection metadata; refuse to
      mix vector spaces (document-assistant `chroma_backend`)
- [ ] Prompt-injection sanitising of recalled content
      (document-assistant `context_firewall`)
- [ ] Token-budgeted hook output (rlm-studio `history_context`)
- [ ] Near-duplicate merge by embedding distance at `retain` time
      (the cheap "surprise" gate; Titans / JEPA proxy)
- [ ] Optional cross-encoder reranker behind a port
- [ ] `memkernel retain|recall|consolidate --json` CLI for non-MCP harnesses
      (Pi, Codex, haa scripts)
- [ ] Eval: knowledge-update and abstention categories (LongMemEval-style)

## 0.4 — ecosystem

- [ ] New repo `llm-wiki`: extract CCT's `knowledge/wiki/schema`, linter and
      `scripts/wiki_ingest` into a stdlib-only package; `memkernel[wiki]`
      extra exposes `wiki query` / `wiki lint --health` as tools
- [ ] New `ragkit` rebuilt from `document-assistant/src/rag/` (langchain-free);
      memkernel contributes `ASTChunker` and n-list `rrf_fuse`, then depends
      on it
- [ ] CCT: hooks on the factory, skill text for tiers, feature id tags,
      `MEMKERNEL_WIKI_DIR=knowledge/wiki`
- [ ] haa: `harness/tools/memory.py`, lifecycle hooks, project id derivation

## Later / research

- [ ] Optional background summariser (`SummarizerPort`) for sleep-time
      consolidation (Letta) — opt-in extra, never required
- [ ] Bi-temporal validity intervals (`valid_from`/`valid_to`) beyond the
      single `supersedes` link (Zep/Graphiti)
- [ ] Git-diff-driven invalidation of `code` memories
- [ ] Graph layer with passage nodes and Personalized PageRank for multi-hop
      recall (HippoRAG 2) — only if flat recall shows multi-hop failures
- [ ] Next-state-embedding predictor over harness traces for retrieval
      scoring (JEPA / V-JEPA 2 analogue) — research only

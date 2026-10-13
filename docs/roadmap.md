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

## 0.3 — documents via RLM Studio, lifecycle components, hardening

(see `docs/research/sibling-projects.md`, ADR-009)

- [ ] `DocumentStorePort` + `ReasonerPort` in `core/ports.py`; `document`
      memory type with a local fallback (chunk + hybrid search)
- [ ] `memkernel/adapters/rlmstudio.py` behind the `memkernel[rlm]` extra;
      `ask(ref_id, question, mode="auto")` MCP tool (Direct / RAG / RLM / auto)
- [ ] `consolidate(synthesize=True)` using the reasoner (opt-in)
- [ ] Contribute a sentence-transformers `EmbeddingPort` shim to rlm-studio
- [ ] `memkernel.lifecycle.MemoryLifecycle` (`on_session_start`,
      `on_pre_compact`, `on_post_compact`, `on_session_end`) so hooks and
      haa call one component instead of re-implementing the protocol
- [ ] `procedure` memories as executable skills (Voyager pattern): metadata
      `language`, `entrypoint`, `verified`, `verification_cmd`; `recall`
      by task description; haa runs them in its sandbox

### Hardening with pieces copied from sibling projects

- [ ] BM25 index persistence (document-assistant `bm25_index.save/load`)
- [ ] Embedding-model provenance in Chroma collection metadata; refuse to
      mix vector spaces (document-assistant `chroma_backend`)
- [ ] Prompt-injection sanitising of recalled content
      (document-assistant `context_firewall`)
- [ ] Token-budgeted hook output (rlm-studio `history_context`)
- [ ] Near-duplicate merge by embedding distance at `retain` time
      (the cheap "surprise" gate; Titans / JEPA proxy) — 0.4 reports pairs
      read-only in `health()`; the merge gate is still open
- [ ] Optional cross-encoder reranker behind a port
- [ ] `memkernel retain|recall|consolidate --json` CLI for non-MCP harnesses
      (Pi, Codex, haa scripts)
- [ ] Eval: knowledge-update and abstention categories (LongMemEval-style)

## Cross-repository sequence

Order is by dependency. A step starts when the one it depends on has a
*published* artefact (tag or PyPI release), not when it is merged.

| # | Repo | Deliverable | Depends on | Unblocks |
|---|------|-------------|------------|----------|
| 1 | memkernel | merge this branch, `0.2.0` on PyPI, CHANGELOG | — | CCT `setup.sh --memkernel` without a path; haa pin |
| 2 | ai-wiki | `0.1.0`: move `knowledge/wiki/schema`, `lint-wiki.sh` and `scripts/wiki_ingest` from CCT; `ai-wiki` CLI (`ingest`, `promote`, `query`, `lint`); backends `claude`, `codex`, `cursor`, `test` | nothing in code (extraction) | CCT thin wrapper; `memkernel[wiki]` |
| 3 | rlm-studio | publish `1.0.0` **as is**; freeze `interact()`, mode names, `StoragePort`, `EmbeddingPort`, `RLMKitClient` as the public contract | — | `memkernel[rlm]` from PyPI |
| 4 | memkernel | `0.3.0`: `DocumentStorePort`, `ReasonerPort`, `document` type, `ask`, `MemoryLifecycle`, rlm-studio adapter, ai-wiki extra | 1, 2, 3 | haa, CCT, rlm-studio hybrid requirements |
| 5 | rlm-studio | `1.1.0`: hybrid mode defined from `ask()` traces (retrieval-seeded RLM with an escalation ladder) | 4 (usage data) | memkernel `ask(mode="hybrid")` |
| 6 | haa | memory component + lifecycle wiring; sandbox-executed `procedure` skills | 4 | the component-assembly UI |
| 7 | code-copilot-team | consume ai-wiki and memkernel 0.3: hooks on the factory, skill text, `MEMKERNEL_WIKI_DIR`, bump dogfood SHA | 2, 4 | — |
| 8 | document-assistant → ragkit | relicense, extract `src/rag/` into the new `ragkit`, memkernel contributes `ASTChunker`/`rrf_fuse` | licensing decision | memkernel 0.4 depends on ragkit |

Steps 2 and 3 run in parallel with 1. Step 8 is last because nothing above
is blocked on it.

## 0.4 — code revalidation, store health (shipped)

- [x] `MemoryService.revalidate()`: whole-file hash check of `code` snapshots,
      `needs_review` flag, recall exclusion, `consolidate(revalidate=True)`,
      session-start section, `POST /revalidate`
- [x] Sourced-code identity `(source, hash)`, owner-specific chunk records,
      automatic supersession by path with a durable `superseded_by` marker
- [x] `MemoryService.health()`: orphans, dangling links, unmarked supersessions,
      stale sources, needs-review, expired-but-present, near-duplicates;
      `GET /health/store`, summary in `memory://status` and `consolidate()`
- [ ] Health fix mode (first action: backfill `superseded_by` for 0.2/0.3 links)
- [ ] Per-chunk range invalidation (0.4 hashes whole files)

## 0.5 — ecosystem

- [ ] `ai-wiki`: extract CCT's `knowledge/wiki/schema`, linter and
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
- [x] Git-diff-driven invalidation of `code` memories — shipped in 0.4 as
      whole-file hash revalidation (no git dependency); per-chunk ranges open
- [ ] Graph layer with passage nodes and Personalized PageRank for multi-hop
      recall (HippoRAG 2) — only if flat recall shows multi-hop failures
- [ ] Next-state-embedding predictor over harness traces for retrieval
      scoring (JEPA / V-JEPA 2 analogue) — research only

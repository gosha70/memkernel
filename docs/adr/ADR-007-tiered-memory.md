# ADR-007: Tiered memory with supersession for facts and decay for experience

Status: accepted (2026-10-11). Earlier ADRs (1–6) are referenced in code
comments (ADR-5: dedup on content hash + type) and predate this directory.

## Context

memkernel 0.1 had four memory types in one flat store with a single TTL
(`episode` expires after 30 days, everything else never). Retrieval was by
hybrid relevance only. Nothing promoted a short-lived observation into
durable knowledge, nothing distinguished a replaced decision from a current
one, and a frequently useful episode expired on the same schedule as noise.

The literature (see `docs/research/memory-literature-review.md`) converges
on three points: facts and experiences need different persistence rules
(Roynard 2026, Zep's bi-temporal invalidation); recall should strengthen
retention and recency should be measured from last access (MemoryBank,
Generative Agents); consolidation is a repeated pass with the LLM doing the
synthesis (Letta, Mem0, A-MEM).

## Decision

1. Introduce `MemoryTier` = {working, short_term, long_term} and derive it
   from `MemoryType`:
   - long-term: `decision`, `convention`, `fact`, `code`, `procedure`
   - short-term: `episode`, `observation`
   - working: `task`
2. Long-term memories never expire; they are replaced via
   `retain(supersedes=<ref_id>)` and superseded records are hidden from recall.
   *0.4 note (spec memkernel-0-4, FR-008):* for `code` memories supersession
   is automatic by `source` — retaining a changed file supersedes every live
   snapshot of that path — and every superseded record of any type carries a
   durable `superseded_by` marker that recall, listing, consolidation and
   the wiki exporter honour independently of the search window.
3. Short-term and working memories expire after a base TTL that grows with
   every recall (`base × (1 + access_boost × access_count)`), measured from
   the later of creation and last access.
4. Recall re-scores the fused hybrid result by
   `w_rel·relevance + w_rec·recency + w_imp·importance`; long-term memories
   have no recency decay.
5. Promotion is agent-driven: `promote(ref_id, type, content)` creates a
   new record with `promoted_from` provenance. `consolidate()` purges expired
   memories and ranks candidates by `importance × (1 + access_count)`.
   memkernel has no LLM dependency.
6. New metadata (`tier`, `importance`, `access_count`, `last_accessed`,
   `tags`, `supersedes`, `promoted_from`) is optional on read: records
   written by 0.1.x load with derived defaults.

## Alternatives considered

- **Keep one tier, add more TTLs.** Simpler, but it leaves facts decaying
  and gives no path from observation to knowledge.
- **LLM-driven consolidation inside the server** (Mem0-style ADD/UPDATE/
  DELETE). Better quality per pass, but it pulls an LLM client into an MCP
  server whose client already is an LLM, doubles token cost, and ties
  memkernel to a provider. Left as an optional extra on the roadmap.
- **Knowledge graph with PPR** (HippoRAG 2, Graphiti). Strongest for
  multi-hop questions; deferred until the flat tiered store shows multi-hop
  failures on real coding sessions. The `supersedes` link is the minimal
  bi-temporal edge.
- **Separate collections per tier.** Cleaner isolation, but it breaks
  cross-tier recall and the idempotent dedup key. Metadata filtering within
  one collection was chosen.

## Consequences

- MCP surface grows from 4 to 9 tools (under the FR-013 limit of 10).
- `recall` and `get` now write (access tracking). Maintenance paths pass
  `touch=False`.
- Hooks become consolidation points; `templates/hooks/` gained
  `session-start.py` and the existing hooks surface promotion candidates.
- Embedders should build the service through `memkernel.factory.build_service`.
- Open follow-ups: embedding-distance near-duplicate merge, BM25 persistence,
  a knowledge-update/abstention eval category, optional background summariser.

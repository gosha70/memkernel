# Short- and long-term memory for coding agents

Status: implemented in memkernel 0.2 (this branch). Revised 2026-10-11.

This document is the design behind the tiered memory model in `memkernel`.
It states the problem, the cognitive-science framing, what the 2024–2026
literature says actually works, and how each mechanism maps onto the code.
The supporting literature review is in
[`../research/memory-literature-review.md`](../research/memory-literature-review.md);
the decision records are ADR-007 (tiers) and ADR-008 (LLM wiki) under
[`../adr/`](../adr/).

## 1. Problem

An agentic coding harness (Claude Code, `code-copilot-team`, `haa`) runs
many sessions over the same repository. Each session has a bounded context
window that is compacted or discarded, so three kinds of knowledge are lost:

| Lost knowledge | Example | Cost of losing it |
|---|---|---|
| What the agent is doing right now | the plan, the current sub-task, open questions | compaction mid-task derails the session |
| What happened recently | tool outputs, test failures, findings | the next session re-discovers the same facts |
| What the project *is* | decisions, conventions, build commands, learned procedures | every session re-derives (or contradicts) project knowledge |

memkernel 0.1 stored all of these in one flat vector store with a single
`episode` TTL. Every memory type was retrieved by relevance alone, nothing
ever got promoted, and nothing distinguished "a fact that is still true"
from "an event that happened once".

## 2. Framing: three tiers, three persistence rules

The model follows the CoALA vocabulary (working / episodic / semantic /
procedural memory, Sumers et al. 2023) and adopts the central correction
from Roynard 2026 (*The Missing Knowledge Layer*): **facts must be
superseded, never decayed; experiences decay; working state is ephemeral.**

```
            ┌──────────────────────────────────────────────────────────┐
  LONG-TERM │ decision · convention · fact · code · procedure           │ never expires;
  (semantic │ importance 0.6–0.9 · no recency decay                    │ replaced via `supersedes`;
  procedural)│ human-readable twin: the LLM wiki (ADR-008)              │ curated by consolidation
            └───────────────▲──────────────────────────────────────────┘
                            │ promote(ref_id, type, content)   ← agent does the synthesis
            ┌───────────────┴──────────────────────────────────────────┐
  SHORT-TERM│ episode · observation                                    │ TTL 30d / 7d, extended
  (episodic)│ importance 0.3–0.4 · recency half-life 7d                │ by every recall (rehearsal);
            │ checkpoints are episodes with checkpoint=true            │ purged by consolidate()
            └───────────────▲──────────────────────────────────────────┘
                            │ retain(type="task") at plan/milestone boundaries
            ┌───────────────┴──────────────────────────────────────────┐
  WORKING   │ task                                                     │ TTL 24h; the agent's
            │ importance 0.5 · half-life 12h                           │ scratchpad for *this* job
            └──────────────────────────────────────────────────────────┘
```

Every `MemoryType` belongs to exactly one tier (`TYPE_TIER` in
`core/models.py`). Callers choose a type; the tier, default importance and
decay policy follow. This keeps the MCP surface small (the agent never
reasons about tiers unless it wants to filter by one).

### Why the slow/fast split matters (HRM, TRM)

The Hierarchical Reasoning Model (Wang et al. 2025) couples a slow
high-level module that updates once per cycle with a fast low-level module
that runs to a local equilibrium under a fixed high-level state. The ARC
Prize re-analysis found the *outer refinement loop with supervision at each
pass* mattered more than the hierarchy itself. The memory analogue we adopt:

- the **working tier** is the fast state. It churns within a task and may be
  reset at a task boundary;
- the **long-term tier** is the slow state. It changes only from the
  *settled* result of a short-term phase, through an explicit `promote`;
- **consolidation is a repeated refinement pass**, not a one-shot write:
  `consolidate()` re-scores short-term memories on every session boundary and
  compaction event and asks the agent to rewrite the keepers.

### What JEPA contributes (and what it does not)

JEPA-style models predict the *embedding of the next state* rather than
the next token, and use prediction error as a signal (V-JEPA 2 plans in
latent space; Titans gates memory writes by "surprise"). We do not train a
predictor. We take the cheap proxy that falls out of it: a new memory whose
embedding is near an existing one is low-surprise and is deduplicated or
merged (`find_by_hash` today, embedding-distance merge is on the roadmap);
retrieval ranks by a combination of axes rather than cosine alone.

## 3. Mechanisms and where they live

| Mechanism | Source | Implementation |
|---|---|---|
| Tiered types with per-tier persistence | CoALA; Roynard 2026 | `core/models.py` (`MemoryTier`, `TYPE_TIER`, `DEFAULT_IMPORTANCE`) |
| Supersession instead of deletion for facts | Zep/Graphiti bi-temporal edges | `retain(supersedes=...)`; `_filter_live` hides superseded records; wiki import supersedes changed pages |
| Ebbinghaus retention strengthened by recall | MemoryBank (Zhong et al. 2023) | `memory/lifecycle.py::effective_ttl_days` (`base × (1 + access_boost × access_count)`), `_touch` on `recall`/`get` |
| Recency decays from last *access*, not creation | Generative Agents (Park et al. 2023) | `recency_score` uses `last_accessed`; per-tier half-life |
| relevance + recency + importance scoring | Generative Agents | `retrieval/search.py::rescore`; weights in settings |
| Importance per record | Generative Agents | `importance` metadata; defaults per type; caller may override |
| Consolidation as a pass that ranks what the agent kept using | Letta sleep-time compute; LangMem background manager | `MemoryService.consolidate` (ranks by `importance × (1 + access_count)`, purges expired) |
| Agent-driven promotion with provenance | Reflexion / ReasoningBank distillation | `MemoryService.promote` (new record, `promoted_from` link) |
| Procedural memory as a first-class type | Voyager skill library; Agent Workflow Memory | `MemoryType.PROCEDURE` → wiki `workflow` pages |
| Compaction and session start as consolidation triggers | Claude Code auto-memory & compaction behaviour | `templates/hooks/{pre-compact,post-compact,session-start}.py` |
| Human-readable compiled knowledge with an index | Karpathy LLM Wiki; Claude Code `MEMORY.md` index | `memkernel.wiki` (ADR-008) |
| Backward compatibility with 0.1.x stores | — | adapter derives tier/importance when metadata is absent |
| Revalidation of code snapshots against their source | Roynard 2026 (facts refreshed against drifting sources) | `MemoryService.revalidate()` (whole-file hash, `needs_review`, hidden from recall), `consolidate(revalidate=True)`, session start |
| One live snapshot per path, durable supersession | ADR-007 supersession model | `retain(type=code)` supersedes by `source`; `superseded_by` marker honoured by recall, listing, consolidation, wiki export |
| Store health audit (read-only) | — | `MemoryService.health()`: orphans, dangling links, stale sources, near-duplicates…; `GET /health/store`, summary in `memory://status` |

### Recall scoring

```
relevance  = min-max normalised RRF(dense cosine, BM25) over the fused candidates
recency    = exp(-ln2 · age_days / half_life(tier))     (1.0 for long-term)
final      = w_rel·relevance + w_rec·recency + w_imp·importance
```

Defaults: `w_rel=1.0, w_rec=0.3, w_imp=0.3`. The weights are settings, so a
harness that only wants pure relevance sets the other two to zero.

### Forgetting

```
ttl(memory) = base_ttl(type) × (1 + access_boost × access_count)
expired     = now − max(timestamp, last_accessed) > ttl
```

| Type | base TTL | half-life |
|---|---|---|
| task | 24 h (`task_ttl_hours`) | 12 h |
| observation | 7 d (`observation_ttl_days`) | 7 d |
| episode | 30 d (`episode_ttl_days`) | 7 d |
| long-term types | none | none |

Expired memories are hidden from `recall` immediately and deleted by
`forget_expired()` / `consolidate()`.

## 4. The division of labour: server bookkeeping, agent synthesis

memkernel deliberately has **no LLM in the loop**. Every system in the
literature that consolidates well (Mem0's ADD/UPDATE/DELETE, A-MEM's note
evolution, Generative Agents' reflections) uses an LLM to do it. In an MCP
server the client *is* the LLM, so:

- the server does what is deterministic and cheap: scoring, decay, dedup,
  provenance, purging, ranking promotion candidates, compiling drafts;
- the agent does what needs judgement: deciding what a short-term memory
  *means*, writing the distilled long-term content, choosing its type.

This keeps memkernel dependency-light (no litellm, no langchain) and makes
it usable from any harness. An optional `SummarizerPort` for background
("sleep-time") consolidation is on the roadmap and will be an opt-in
extra, never a requirement.

## 5. MCP surface (9 tools, FR-013 limit is 10)

| Tool | Tier | Purpose |
|---|---|---|
| `retain(content, type, …, importance, tags, supersedes)` | any | store; idempotent on content+type (`code`: on source+content, supersedes by path) |
| `recall(query, type, tier, session_id, checkpoint_only, top_k, include_needs_review)` | any | ranked references; records access |
| `get(ref_id)` | any | full content; records access |
| `forget(ref_id)` | any | delete |
| `promote(ref_id, type, content, importance, tags)` | short → long | agent-driven consolidation with provenance |
| `consolidate(session_id, limit, synthesize, revalidate)` | short/working | purge expired, return promotion candidates (+ health summary, optional revalidation) |
| `ask(ref_id, question, mode)` | any | answer a question about one memory through the reasoner port |
| `wiki_export(wiki_dir)` | long | compile long-term memories to draft wiki pages |
| `wiki_import(wiki_dir)` | long | index curated wiki pages |

## 6. Session protocol (what the harness should do)

1. **Session start** (hook): `consolidate()` → recover latest checkpoint →
   `recall(tier=long_term)` for the task → mention the wiki index.
2. **During work**: `retain(type=task)` at plan changes; `retain(type=observation)`
   for findings; `retain(type=decision|convention|fact|procedure)` only for
   things that are true beyond this session (the agent may `promote` later
   instead of deciding now).
3. **Before compaction** (hook): checkpoint as `episode(checkpoint=true)`;
   `consolidate()` to surface candidates.
4. **After compaction** (hook): latest checkpoint + long-term context +
   promotion candidates are injected; the agent calls `promote` for keepers.
5. **Periodically** (curator or CI): `wiki_export` → review drafts →
   `wiki_import` so the curated pages are the ones recall finds.

## 7. Non-goals for this iteration

- A knowledge graph layer (HippoRAG-style PPR). Deferred until the flat
  tiered store shows multi-hop failures on real sessions.
- Training a JEPA/Titans-style predictor over harness traces. Research
  direction only.
- Replacing Claude Code's own auto-memory. memkernel complements it: auto
  memory is the per-user notebook; memkernel is the per-project, multi-agent,
  queryable store.

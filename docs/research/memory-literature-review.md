# Memory management for LLM agents: literature review (2024–2026)

Compiled 2026-10-11 for the memkernel tiered-memory redesign. Primary sources
were read where the environment allowed; where a number comes from a
secondary summary it is marked. The review is organised by what each source
contributes to a *code-aware memory server used by coding agents*.

## 1. Hierarchical reasoning: HRM and TRM

**HRM** — Wang et al., *Hierarchical Reasoning Model*, arXiv 2506.21734 (2025).
A 27M-parameter recurrent model with two coupled modules running at different
timescales: a low-level module updates every step under a fixed high-level
state; the high-level module updates once per cycle from the low-level
module's settled state ("hierarchical convergence", which avoids the early
fixed-point collapse of plain RNNs). Trained without BPTT via a one-step
gradient approximation, deep supervision per segment, and adaptive
computation time (a Q-head decides halt/continue). Reported ~40% ARC-AGI-1,
near-perfect Sudoku-Extreme/Maze-Hard.

*Contested*: the ARC Prize team reproduced the numbers but found the
hierarchy contributed little versus a same-size transformer; the outer
refinement loop with per-pass supervision drove the gains
(arcprize.org/blog/hrm-analysis, Aug 2025). A 2026 mechanistic study
(arXiv 2609.22197) finds component roles vary by task.

**TRM** — Jolicoeur-Martineau, *Less is More: Recursive Reasoning with Tiny
Networks*, arXiv 2510.04871. Drops the two-module hierarchy for one 2-layer
~7M network that keeps an answer `y` and a latent scratchpad `z`, refines `z`
several times, then updates `y` once per cycle. Reported 44.6–45% ARC-AGI-1
(secondary summaries).

*Transfer to memory (by analogy, speculative)*: two timescales → planning
state updated at milestone boundaries, execution state free to be compacted;
the ARC Prize finding → repeated consolidation passes that re-score and
rewrite notes matter more than storage hierarchy; ACT halting → spend more
retrieval/reflection compute when uncertainty is high.

## 2. JEPA and the "knowledge layer" critique

**JEPA mechanics** (rohitbandaru.github.io/blog/JEPA-Deep-Dive). A context
encoder embeds the visible input, an EMA target encoder embeds the masked
part, and a predictor regresses the target embedding from the context
embedding. Predicting in representation space lets the model ignore
unpredictable detail; EMA + stop-gradient prevents collapse. **V-JEPA 2**
(arXiv 2506.09985) freezes a 1.2B video encoder and trains an
action-conditioned predictor to forecast the next state embedding; planning is
MPC over latent distance to a goal embedding. **LLM-JEPA** (arXiv 2509.14252)
adds a JEPA loss to next-token training over naturally paired views
(code ↔ NL description).

**arXiv 2604.11364 is not a JEPA paper.** It is Roynard, *The Missing
Knowledge Layer in Cognitive Architectures for AI Agents* (v2 June 2026).
It argues that both CoALA and JEPA-style systems lack a knowledge layer with
its own persistence semantics: facts are either compressed lossily into
weights, held in short-term buffers, or given the same decay mechanics as
episodic memory. Proposal: four layers with distinct rules — Knowledge
(indefinite supersession, never decays), Memory (Ebbinghaus decay), Wisdom
(evidence-gated revision), Intelligence (ephemeral orchestration). Status:
single-author preprint with Python/Rust reference implementations; no
independent evaluation found. **memkernel adopts the supersession-vs-decay
split directly** (ADR-007).

*"Predict the next state embedding" for memory*: established in V-JEPA 2-AC
for planning; speculative for text memories. Cheap proxies: (i) a memory
well predicted (near) an existing one is redundant → merge; (ii) a poorly
predicted one is novel → keep (Titans' surprise gate); (iii) rank candidates
by distance to a predicted *next-state* embedding rather than the query.
No published agent-memory system trains such a predictor over harness traces.

## 3. Agent memory systems

| System | Key mechanism | What memkernel takes |
|---|---|---|
| **MemGPT / Letta** (arXiv 2310.08560) | OS analogy: main context (working context block + FIFO queue) vs external (recall log, archival vector DB); LLM pages data in; memory-pressure warning at ~70%, flush + recursive summary at 100% | compaction hooks as the "page-out" event; working tier as the editable block |
| **Letta sleep-time compute** (arXiv 2504.13171) | a background agent rewrites memory blocks during idle time; up to 5× less test-time compute | `consolidate()` as the deterministic half; optional background summariser on roadmap |
| **Mem0** (arXiv 2504.19413) | extract candidate facts, then ADD/UPDATE/DELETE/NOOP against top-10 similar memories; LoCoMo J 66.9% at 1.8K tokens vs 72.9% full context at 26K. *2026: the README now describes an ADD-only single pass* | explicit `supersedes` as the UPDATE; git diffs as a free DELETE trigger for `code` (roadmap) |
| **A-MEM** (arXiv 2502.12110) | Zettelkasten notes with LLM-generated context/keywords/tags; new notes link to similar ones and can rewrite older notes' attributes | tags + provenance links (`promoted_from`, `supersedes`) |
| **Zep / Graphiti** (arXiv 2501.13956) | episodes → entities/edges → communities; **bi-temporal** edges (valid_at/invalid_at, ingested_at); contradictions invalidate, never delete; fusion of cosine + BM25 + graph BFS | invalidate-don't-delete (`supersedes`), hybrid fusion (already present) |
| **HippoRAG 1/2** (arXiv 2405.14831, 2502.14802) | OpenIE KG as a hippocampal index; Personalized PageRank from query concepts; v2 adds passage nodes and LLM "recognition memory" filtering | deferred (graph layer is a non-goal this iteration) |
| **Generative Agents** (Park et al. 2023) | retrieval score = recency (0.995^hours since last *retrieval*) + importance (LLM 1–10) + relevance, min-max normalised; reflection when accumulated importance > threshold | the three-axis `rescore`, importance metadata, recency from last access |
| **Titans** (arXiv 2501.00663) | test-time learned memory gated by gradient "surprise" with momentum and a forget gate | surprise-as-write-gate on roadmap (embedding distance proxy) |
| **MemoryBank** (arXiv 2305.10250) | Ebbinghaus retention R = e^(−t/S), S incremented on each recall | `effective_ttl_days` reinforcement by `access_count` |
| **LangMem** (2025) | semantic / episodic / procedural types; hot-path tools vs background manager | type taxonomy; hooks as the background path |
| **Reflexion / Voyager / AWM / ReasoningBank** | procedural memory as verbal reflections, verified skills, induced workflows, self-judged strategy items (+8.3% WebArena, evaluated on SWE-Bench-Verified) | `MemoryType.PROCEDURE`; promotion only after the agent judges the outcome |
| **Claude Code** (code.claude.com/docs/en/memory) | CLAUDE.md hierarchy; auto memory `~/.claude/projects/<project>/memory/` with a `MEMORY.md` index (first 200 lines / 25 KB loaded), topic files on demand, four note types (`user`, `feedback`, `project`, `reference`); compaction reloads CLAUDE.md and auto memory from disk | hooks on SessionStart/PreCompact/PostCompact; the wiki index as the "MEMORY.md" of project knowledge |
| **Claude API memory tool + context editing** | client-side file memory tool (`memory_20250818`); `clear_tool_uses`, server-side `compact` | treat compaction as a consolidation trigger; expire unaccessed files |

## 4. Benchmarks

- **LoCoMo** (ACL 2024): 10 multi-session conversations; single-hop,
  multi-hop, temporal, open-domain, adversarial. Vendor numbers (90+) use
  different judges and are not comparable.
- **LongMemEval** (ICLR 2025, arXiv 2410.10813): 500 questions over
  information extraction, multi-session reasoning, temporal reasoning,
  **knowledge updates**, **abstention**; ~30% accuracy drop for commercial
  assistants. The update/abstention categories are where memory systems
  diverge most.
- **MemBench** (ACL Findings 2025, arXiv 2506.21605): factual vs reflective ×
  participation vs observation; scores effectiveness, efficiency (number of
  memory operations) and capacity (degradation as the store grows).
- Coding-specific and immature: SWE-Bench-CL (arXiv 2507.00014),
  VibeMemBench (arXiv 2609.23570), SWE-MeM (arXiv 2606.28434).

memkernel's `eval/run_eval.py` should grow a *knowledge-update* and an
*abstention* category before any headline retrieval number is trusted.

## 5. Cognitive-science framing

CoALA (arXiv 2309.02427): working memory persists across LLM calls;
episodic (past trajectories), semantic (facts), procedural (code/skills)
long-term stores, after ACT-R/Soar. Episodic → semantic **consolidation**
appears as reflection (Generative Agents), update ops (Mem0), note evolution
(A-MEM), sleep-time agents (Letta) and distillation (ReasoningBank).
**Forgetting curves**: MemoryBank's Ebbinghaus; Generative Agents' per-hour
decay from last retrieval; Titans' learned forget gate. Roynard's point:
decay is right for experience and wrong for facts.

## 5a. CoALA / ReAct / Voyager as the harness blueprint

The owner's *Architectural Frameworks for Language Agents* report stacks
three ideas: CoALA as the taxonomy (working memory vs episodic / semantic /
procedural long-term memory; internal actions = reasoning, retrieval,
learning; external = grounding), ReAct as the runtime loop (thought →
action → observation), Voyager as the lifelong-learning pattern (a library
of self-written, verified, embedded-by-description executable skills).
Mapping onto this design:

| Report element | memkernel / haa |
|---|---|
| Working memory (context window + scratchpad) | `task` tier + the harness's message list |
| Episodic LTM | `episode`, `observation` |
| Semantic LTM (RAG knowledge base, corporate wiki) | `fact`, `decision`, `convention`; wiki bridge; documents via RLM Studio (ADR-009) |
| Procedural LTM (skill library) | `procedure`; executable-skill metadata is roadmap 0.3 |
| Retrieval action | `recall`, `get`, `ask` |
| Learning action | `retain`, `promote`, `consolidate` |
| ReAct loop | haa's `cct.py`; Claude Code's own loop |
| Sandbox for skill verification | haa's Docker sandbox; RLM Studio's sandbox adapters |

The report's own trade-off column is worth keeping in mind: ReAct "explodes
context window consumption" (hence tiers and `ask` instead of `get`), and
Voyager "requires securely isolated code execution" (hence skills execute
in haa's sandbox, never in memkernel).

## 6. Design implications adopted (see memory-tiers.md §3)

1. Separate persistence semantics by record kind: facts supersede, episodes
   decay, working state is ephemeral.
2. Invalidate-don't-delete for facts (`supersedes`).
3. Recency from last access; retention strengthened by recall.
4. relevance + recency + importance scoring with configurable weights.
5. Consolidation as a repeated pass at session boundaries and compaction.
6. Procedural memory as a first-class type, promoted only after judged success.
7. A small always-loadable index (the wiki `index.md`) with on-demand detail.
8. The server does bookkeeping; the agent does synthesis (no LLM in memkernel).

Deferred: graph layer with PPR (HippoRAG 2), surprise-gated writes (Titans),
bi-temporal validity intervals beyond a single `supersedes` link, and
knowledge-update/abstention evaluation categories.

## Primary links

HRM arxiv.org/abs/2506.21734 · TRM arxiv.org/abs/2510.04871 · ARC Prize
arcprize.org/blog/hrm-analysis · Roynard arxiv.org/abs/2604.11364 · JEPA
rohitbandaru.github.io/blog/JEPA-Deep-Dive · V-JEPA 2 arxiv.org/abs/2506.09985 ·
LLM-JEPA arxiv.org/abs/2509.14252 · MemGPT arxiv.org/abs/2310.08560 ·
Sleep-time arxiv.org/abs/2504.13171 · Mem0 arxiv.org/abs/2504.19413 · A-MEM
arxiv.org/abs/2502.12110 · Zep arxiv.org/abs/2501.13956 · HippoRAG
arxiv.org/abs/2405.14831, arxiv.org/abs/2502.14802 · Generative Agents
arxiv.org/abs/2304.03442 · Titans arxiv.org/abs/2501.00663 · MemoryBank
arxiv.org/abs/2305.10250 · AWM arxiv.org/abs/2409.07429 · ReasoningBank
arxiv.org/abs/2509.25140 · Reflexion arxiv.org/abs/2303.11366 · CoALA
arxiv.org/abs/2309.02427 · LongMemEval arxiv.org/abs/2410.10813 · MemBench
arxiv.org/abs/2506.21605 · Claude Code memory code.claude.com/docs/en/memory ·
Claude memory tool platform.claude.com/docs/en/agents-and-tools/tool-use/memory-tool

# Integrating memkernel into code-copilot-team and haa

Status: plan (2026-10-11). Both targets were surveyed from their current
`master`; paths below are theirs.

## code-copilot-team (CCT)

CCT already ships a memkernel integration (`specs/memkernel-integration`,
feature `memkernel-memory`, maturity *experimental*): the on-demand skill
`shared/skills/memkernel-memory/SKILL.md`, three hooks
(`memkernel-recall`, `memkernel-pre-compact`, `memkernel-post-compact`), a
launcher that writes `mcpServers.memkernel` into `.claude/settings.local.json`
with a per-project `MEMKERNEL_PROJECT_ID`, `setup.sh --memkernel <path>`
(editable pip install), a Pi MCP backend declaration, and a dogfood
benchmark adapter pinned to a memkernel SHA.

What changes with memkernel 0.2:

1. **Hooks → factory.** CCT's `.py` hooks assemble `MemoryService` from
   memkernel internals (`ChromaVectorStore`, `SentenceTransformerEmbedding`,
   `BM25Index`, `HybridSearchService`, `ASTChunker`). Replace the body of
   each `build_service()` with `from memkernel.factory import build_service`.
   The 0.1 constructor signatures are unchanged in 0.2, so this is not
   urgent, but it is the only supported path going forward. memkernel's
   `templates/hooks/` are the upstream of these copies and now show the
   pattern, including the new `session-start.py` (CCT's `memkernel-recall`).
2. **Skill update.** `memkernel-memory/SKILL.md` gains the tier vocabulary:
   `task` for the current plan, `observation` for findings, `fact`/`procedure`
   for durable knowledge, `promote` after a phase completes, `consolidate` at
   phase boundaries. Draft text is in `templates/claude-memory-instructions.md`.
3. **Phase agents.** CCT's Research → Plan → Build → Review phases run in
   separate sessions and hand off through files (`specs/<id>/plan.md`,
   `collaboration/build-review.md`, `phase-*-recap.md`). Those files remain
   the authoritative handoff; memkernel adds: `retain(type=task)` by Plan,
   `retain(type=observation)` by Build/Review, and the `phase-recap` agent
   calling `promote` for decisions and `retain(type=procedure)` for
   workflows that worked. Tag every memory with the feature id
   (`tags=["feature:<id>", "phase:<name>"]`) so `recall` can be scoped.
4. **Wiki.** Set `MEMKERNEL_WIKI_DIR=knowledge/wiki`. `wiki_import` after
   `scripts/wiki promote` keeps recall aligned with the curated wiki;
   `wiki_export` writes drafts that CCT's promote flow can review. Pages
   compiled by memkernel pass `knowledge/wiki/scripts/lint-wiki.sh`
   (frontmatter, slug, sources, index reachability) by construction.
5. **Pi / non-MCP harnesses.** CCT marks Pi "unsupported" pending MCP
   transport. A thin CLI (`memkernel retain|recall|consolidate --json`) is on
   the memkernel roadmap so Pi and Codex can call it as a subprocess.
6. **Namespaces.** One `MEMKERNEL_PROJECT_ID` per project root is kept.
   Sub-agent scratch is separated by `session_id` (the launcher should pass
   the Claude Code session id, not a checkpoint timestamp) and by the
   `working` tier, which expires in 24h.

Verification in CCT: the existing `tests/test-hooks.sh` guard tests, plus a
session that retains an observation, triggers `/compact`, and sees the
promotion candidate in the post-compaction injection.

## haa

haa is a ReAct loop over an OpenAI-compatible endpoint with a Docker sandbox
and `harness/memory/agents_md.py` (an `AGENTS.md` file injected as a system
message) as its only memory. `chromadb` is pinned but unused; roadmap items
6–7 are "ChromaDB-backed memory" and "session persistence and context
compaction". The owner has just started the context-management work and
intends haa to become a **component-assembly harness**: a developer picks
and wires memory, sandbox, tools, workflow and provider components into a
customised harness, later through a UI.

That intent sets a requirement on memkernel: every capability must be
available as a Python component with a small, stable interface, not only
as MCP tools. Concretely (roadmap 0.3): `build_service()` (done), the
ports in `core/ports.py` (done; `DocumentStorePort`/`ReasonerPort` to
come), and a `MemoryLifecycle` component exposing
`on_session_start() -> str`, `on_pre_compact(summary) -> str`,
`on_post_compact() -> str`, `on_session_end(summary) -> None`, which is
what the Claude Code hooks already do in script form. haa then assembles
memory by instantiating `MemoryLifecycle(build_service())` and calling it
from its loop; a future UI assembles the same objects from configuration.

In CoALA terms (see the owner's *AI Harness Architectures* report):
haa's loop is the ReAct decision cycle, memkernel is the memory module
with Retrieval (`recall`/`ask`) and Learning (`retain`/`promote`) as the
internal actions, and `procedure` memories are the Voyager skill library
once they carry executable metadata.

Plan (lowest-friction, in-process Python, no MCP client needed):

1. `requirements.txt`: replace `chromadb>=0.5` with `memkernel>=0.2` (or a
   git URL until memkernel is on PyPI).
2. `harness/tools/memory.py`: register `retain`, `recall`, `get`, `promote`,
   `consolidate` with haa's `@tool` registry, each delegating to a module-level
   `MemoryService` built by `memkernel.factory.build_service()`. Memory tools
   run host-side like the filesystem tools (the sandbox cannot see host
   packages). Persist to a path outside the bind-mounted `workspace/`
   (e.g. `MEMKERNEL_CHROMA_PERSIST_PATH=.memkernel/chroma` next to `harness/`).
3. `harness/cct.py` lifecycle:
   - after `load_agents_md()`: run the equivalent of `session-start.py` and
     append its output as a system message;
   - when `tool_rounds` hits `MAX_TOOL_ROUNDS` (haa's de-facto compaction
     trigger today): `retain(type=episode, checkpoint=True)` with a model
     written summary, then `consolidate()`;
   - in the `finally` block: retain a session summary and run
     `consolidate()`.
4. `harness/resources/system-prompt.txt` "# Memory management" section:
   paste the minimal block from `templates/claude-memory-instructions.md`.
   `AGENTS.md` stays as the human-edited rules file; durable *learned*
   knowledge goes through `promote` and, later, `wiki_export`.
5. `MEMKERNEL_PROJECT_ID` derives from `WORKSPACE_DIR` (slug + short hash,
   the same scheme CCT's launcher uses) so haa and Claude Code share memory
   for the same repo.

Verification in haa: a pytest that builds the service with an ephemeral
Chroma client and a mock embedder (memkernel's `tests/conftest.py`
`MockEmbedding` shows how), calls each tool function, and checks a
`consolidate()` report after a forced budget overflow.

## Open-sourcing memkernel

- Apache-2.0 (relicensed 2026-10-11), CI with lint/type/test/security/build. Missing for a release:
  PyPI publication (CCT's spec notes "pre-publication uses pip install -e"),
  a CHANGELOG, and a `CONTRIBUTING.md`.
- Publish `0.2.0` once this branch merges; CCT's `setup.sh --memkernel` then
  works without a path argument and haa can pin a version.

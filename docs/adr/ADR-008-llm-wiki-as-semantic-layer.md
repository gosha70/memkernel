# ADR-008: An LLM wiki is the human-readable form of long-term memory

Status: accepted (2026-10-11).

## Context

Karpathy's LLM Wiki pattern (gist 442a6bf5…, April 2026) replaces
re-deriving knowledge on every query with a persistent, interlinked markdown
wiki that the LLM maintains: `raw/` (immutable sources), `wiki/` (LLM-written
pages), a schema (`CLAUDE.md`/conventions), an `index.md` read first on every
query, an append-only `log.md`, and three operations — ingest, query, lint.
Vellum Labs measured it on a 1,200-line library: 21 pages, ~12 minutes,
$6.96; the wiki is not a cheaper RAG, it is where decisions, rules and
measured results *not present in the source* live.

`code-copilot-team` already runs this pattern: `knowledge/wiki/` with nine
page types, YAML frontmatter with mandatory citations, a structural linter,
and `scripts/wiki_ingest/` (ingest / promote / query / health-lint, 117
tests, stdlib-only, LLM via a subprocess backend). Its own decision record
states that the wiki is *not* session memory and that memkernel-style recall
is complementary.

A vector store is the right home for what is not wiki-worthy (episodes,
observations, working state) and for *finding* things; markdown in git is the
right home for curated, cited, human-reviewed knowledge.

## Decision

1. The long-term semantic tier has two representations that must agree:
   the vector store (queryable, with scores and provenance) and the wiki
   (readable, versioned, cited). **The wiki is the source of truth for
   curated knowledge; the store is its index plus the home of everything
   not yet curated.**
2. `memkernel.wiki` provides the bridge without an LLM:
   - `WikiExporter` compiles long-term memories that have no page into
     *draft* pages (status `draft`, required H2 sections, placeholder text
     for what memory does not record, `memkernel://<project>/<ref_id>`
     citation, `index.md` and `log.md` entries). It never overwrites an
     existing page.
   - `WikiImporter` indexes curated pages as long-term memories tagged
     `wiki`, `page:<slug>`, `page_type:<type>`; unchanged pages dedup,
     changed pages supersede their previous memory, deprecated pages are
     skipped.
   - Page format follows CCT's schema so compiled pages pass its linter.
3. Mapping: `decision`→`decision`, `convention`/`fact`→`concept`,
   `procedure`→`workflow`; `code` is never exported (code lives in the
   repo). Import maps `concept|overview|glossary|incident|open-question`→`fact`,
   `workflow|playbook`→`procedure`.
4. **Repository recommendation.** The wiki maintainer (schema, linter,
   ingest/promote/query/lint CLI) should be extracted from CCT into a new
   standalone repository — working name `gosha70/ai-wiki` — published as a
   Python package with no runtime dependencies beyond the standard library
   and an optional LLM backend. memkernel depends on it as an optional
   extra (`memkernel[wiki]`) for the LLM-driven operations; the bridge in
   this ADR stays in memkernel because it needs the store. CCT and
   document-assistant consume the same package.

## Alternatives considered

- **Put the wiki tooling inside memkernel.** Couples a memory server to
  markdown-maintenance concerns and to an LLM backend; CCT would then depend
  on memkernel for something unrelated to memory.
- **Leave the tooling inside CCT.** It works today, but memkernel and
  document-assistant cannot reuse it, and CCT's own decoupling principle
  (shared sources → generated adapters) argues for extraction.
- **Vector-only, no wiki.** Simplest, but loses human review, citations,
  git history and the index-first navigation that the measured results
  favour for decisions and rules.
- **Wiki-only, no vector store.** Fine at ~hundreds of pages for curated
  knowledge; useless for episodic memory, scoring, decay and multi-agent
  scratch state.

## Consequences

- Two new MCP tools (`wiki_export`, `wiki_import`) and a `MEMKERNEL_WIKI_DIR`
  setting.
- A curation loop appears: export drafts → human/agent curates → import.
  Until `ai-wiki` exists, CCT's `scripts/wiki promote` is the curator.
- Compiled pages carry `memkernel_ref` in frontmatter so a page can be
  traced back to the memory it came from, and imported memories carry the
  page path as `source`.
- Follow-up: the new `ai-wiki` repo (extraction PR against CCT), then
  `memkernel[wiki]` extra wiring `wiki query`/`wiki lint --health` as tools.

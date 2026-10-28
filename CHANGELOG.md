# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

<!-- memkernel 0.6, the Release B wiki bridge parts 1 and 2a (memkernel #48); the 0.5 entries below move to [0.5.0] at the tag. -->

### Changed

- **`wiki_import` is governed when the extra is installed** (wiki-studio 0.7.0
  review state): only pages wiki-studio reports approved are imported, and only
  when their bytes are still the approved revision. A draft, a page that
  declares itself approved, or a page edited after approval is skipped and
  listed in `not_approved`; an edited page keeps its last approved memory until
  it is approved again. **For existing users with the extra this is a behaviour
  change:** `wiki_import` imports nothing until a curator approves pages with
  `wiki-studio approve` (a wiki without wiki-studio's manifest reports
  `manifest_missing`), and drafts imported by earlier versions stay in the
  store: they are the long-term memories tagged `wiki` without a `page_sha:`
  tag. Imported memories carry `page_key:` and `page_sha:` tags, so a second
  import adds nothing. Without the extra the import reads the page files as
  before.
- `memkernel[wiki]` now requires `wiki-studio>=0.7.0,<1`, one floor for export
  and import, and CI tests 0.7.0. An installed wiki-studio older than 0.7.0, or
  one without a call the bridge makes, is refused with `gate_error`
  (upgrade it, or uninstall it to use the direct writer); the export never
  falls back to unchecked writes.
- The gated `wiki_export` no longer snapshots and restores the wiki
  (`_WikiSnapshot` is removed). wiki-studio (since 0.6.0) writes only the paths the
  patch-set names, under its lock, and rolls back its own writes, so a failed
  export cannot revert a page another writer committed during it, as the
  restore could. A failed export to a new wiki now leaves an empty `index.md`
  and `log.md`; in 0.5 it left no files.
- A new wiki's `index.md` and `log.md` on the gated path are wiki-studio's
  scaffold, created by its `init`: `status: stable`, titles `Wiki` and
  `Wiki log`. memkernel's direct writer keeps its own (`status: draft`,
  `Wiki Index`, `Wiki Edit Log`). Pages and the index and log entries are the
  same on both paths; existing wikis are unaffected.

### Added

- The `corrects` frontmatter key: an approved page's comma-separated memory
  `ref_id`s are superseded by the page's memory on import, their records kept.
- `MemoryService.supersede(ref_id, by_ref)`: marks an existing record as
  replaced; idempotent, and it refuses (never overwrites) an unknown record,
  another project's, itself, or one already superseded by another.
- `wiki_import` response keys: `governed`, and when they apply `unchanged`
  (approved pages already current; `skipped` now means only pages that cannot
  be imported), `not_approved`, `corrections`, `unresolved`, `invalid_corrects`
  and `import_error`. The same
  fields are on `ImportReport`; `WikiImporter` takes an optional `project_root`.

- `wiki_export` response keys for a gated export, from wiki-studio's receipt:
  `proposal` (the proposal name), `submission_digest`, and `archived_dir`
  (where wiki-studio archived the proposal; `null` when it committed the pages
  but could not archive it, or failed after committing them: memkernel checks
  each page against the receipt's post-write sha256, or its bytes when the
  receipt is unreadable, and reports such an export as written, not as a
  `gate_error`). `archive_hint` appears only when `archived_dir` is
  `null`, with the `promote` command that finishes the archive and applies
  nothing twice (run through the interpreter memkernel uses). `receipt_error`
  appears when the receipt could not be read; the export still succeeds. The
  same fields are on `ExportReport`.
- README: ignore wiki-studio's lock file next to the wiki directory.

### Fixed

- `wiki_import` matched a page's previous memory by slug, so two pages with the
  same slug in different directories superseded each other's memory; it now
  matches by the page's path.

### Added

- `memkernel[wiki]` extra (ADR-010): wiki-studio as an optional dependency,
  imported lazily and silent when absent. With it installed, `wiki_export`
  returns wiki-studio's lint and health findings for the wiki under `lint`
  (field for field as wiki-studio reports them).
- With wiki-studio 0.3.1 or later, `wiki_export` writes through wiki-studio's
  promote gate: the `index.md`/`log.md` scaffold first (the gate cannot create
  them), then every new page with its index and log lines as one patch-set.
  A rejected or failed export, or a wiki-studio that is installed but broken,
  writes nothing and reports `gate_error` (memkernel restores the files a
  failed promote left part-written); the pages,
  `index.md` and `log.md` of a clean export match the direct writer byte for
  byte. New setting `MEMKERNEL_WIKI_PROPOSALS_DIR` (default
  `.memkernel/wiki-proposals/` under the project root).
- Schema drift test: memkernel's export map and required sections are checked
  against `wiki_studio.schema.PAGE_TYPES`.

### Changed

- `wiki_export` response: new `lint` key (object with the extra, `null`
  without it), `lint_hint` without the extra, and `lint_error` when the
  installed wiki-studio's lint pass fails (the export itself still succeeds).
  The pages, `index.md` and `log.md` it writes are unchanged. This is the
  only behaviour difference without the extra. With the extra, `gate_error`
  appears when wiki-studio's promote gate rejects an export (nothing is
  written then).
- `memkernel[wiki]` now requires `wiki-studio>=0.3.1,<1` (it ships `py.typed`;
  the mypy override is gone). CI tests against wiki-studio 0.4.1.

## [0.4.1] - 2026-10-15

### Added

- README section "What MemKernel is, and what it is not", with an evidence
  line pointing at the retrieval eval and the agent-level benchmark tracked
  in #17 (#18).
- Contract test with [wiki-studio](https://github.com/gosha70/wiki-studio):
  pages written by `WikiExporter` lint clean with `wiki-studio lint --health`
  (wiki-studio is a development dependency only; no runtime change).

### Changed

- Documentation names wiki-studio as the maintainer of the wiki page schema
  (README, roadmap, a dated note in ADR-008); the working name `ai-wiki` is
  retired.

### Fixed

- The server (and `build_service()`) no longer fails to start when the working
  directory holds a `.env` with keys for other tools: the `.env` source of
  `MemKernelSettings` is limited to known settings instead of rejecting the
  file (#15). `MEMKERNEL_` keys that match no setting (typos) are logged as a
  warning, in `.env` and in the environment, instead of being dropped silently;
  unknown constructor arguments still raise.

## [0.4.0] - 2026-10-12

### Added

- Revalidation of `code` memories: `MemoryService.revalidate()` hashes each
  live snapshot's whole source file (inside the `MEMKERNEL_PROJECT_ROOT`
  boundary) against the stored content hash and flags `needs_review` with
  reason `changed` or `missing`; a matching file clears the flag. Flagged
  memories leave default `recall` (`include_needs_review=true` shows them).
  Runs from `consolidate(revalidate=true)`, at session start
  (`### Needs review` section) and from `POST /revalidate`.
- Read-only store health pass: `MemoryService.health()` reports orphans,
  dangling links, unmarked supersessions, stale sources, needs-review,
  expired-but-present records and, in full mode, near-duplicate pairs among
  recent long-term memories. Exposed as `GET /health/store`, as a counts
  summary in `memory://status` and in every `consolidate()` report, and as a
  `### Store health` line at session start.
- Durable supersession: a replaced record carries `superseded_by`, which
  recall, `list_memories`, `consolidate` and the wiki exporter honour
  regardless of the search window; owner-specific code chunk records
  (`<canonical>-chunk-<n>`, `code_chunk`, `parent_ref`).
- Port additions for adapter authors: `VectorStorePort.find_by_hash(...,
  source=None)` (never returns a chunk record) and
  `VectorStorePort.list_all(..., include_content=True)`.
- `memkernel --version` and `memkernel --help` print and exit; any other
  argument is an error (exit 2). Without arguments the command starts the
  MCP server as before.
- Settings `MEMKERNEL_PROJECT_ROOT`, `MEMKERNEL_HEALTH_DUPLICATE_THRESHOLD`,
  `MEMKERNEL_HEALTH_DUPLICATE_LIMIT`, `MEMKERNEL_HEALTH_REPORT_LIMIT`;
  `Memory.needs_review`, `review_reason`, `superseded_by`, `parent_ref`
  (older stores load with defaults).
- `templates/kiro/`: MCP server entry, always-on steering file and lifecycle
  hooks (`SessionStart`, `Stop`, manual checkpoint) for Kiro and the Kiro CLI,
  with a README covering custom agents and the legacy Amazon Q Developer CLI;
  README section "Add to Kiro".

### Changed

- `retain(type="code")` behaviour: a sourced snapshot is identified by
  `(source, content_hash)`, so identical content under another path is its
  own record, and retaining a changed file **supersedes** every live snapshot
  of that path instead of adding a second live record (the old record stays,
  hidden; its chunk records are removed). A dedup hit embeds nothing.
- `recall` gains `include_needs_review`; `consolidate` gains `revalidate`
  and its report always carries `health` (counts) and, when requested,
  `revalidated`; `list_memories` hides superseded records unless
  `include_superseded=True`.
- Hook templates and `templates/kiro/settings/mcp.json` set
  `MEMKERNEL_PROJECT_ROOT`.
- README install guidance: pipx (isolated) recommended over a global pip
  install, supported Python range and the `--python` fix for pipx, absolute
  command and store paths in the Claude Code registration, a troubleshooting
  section, and a note that there is no npm package.

### Fixed

- `memory://status` was registered as a URI template since 0.1 (its handler
  took a `ctx` parameter) and could not be read as a resource; it is now a
  concrete resource.

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
- Port additions for adapter authors: `VectorStorePort.count(where=None)`
  (filtered, ids-only count) and `DocumentStorePort.indexed(doc_id)` (number
  of indexed chunks); both must be implemented by custom backends.

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

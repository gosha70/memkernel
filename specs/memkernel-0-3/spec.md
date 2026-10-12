---
spec_mode: full
feature_id: memkernel-0-3
risk_category: feature
status: approved
date: 2026-10-11
---

# Spec: memkernel 0.3 — documents, ask(), lifecycle component

<!-- Project constitution: shared/skills/ — copilot-conventions, coding-standards, safety -->

Design references (read before building): `docs/adr/ADR-009-rlm-studio-for-documents.md`,
`docs/architecture/memory-tiers.md`, `docs/integration/harness-integration.md`,
`docs/roadmap.md` (section "0.3").

## User Scenarios

### US1: Ports and the `document` memory type (Priority: HIGH)

**Given** a harness that must keep a large artefact (a spec, a transcript, a 2,000-line file) without loading it into the agent's context
**When** the agent calls `retain(content=<body>, type="document", source="specs/x.md")`
**Then** the body is stored through `DocumentStorePort` (the built-in local store by default), its chunks are indexed for hybrid search, and `recall` finds the document by its summary and tags

### US2: `ask()` answers questions about a memory (Priority: HIGH)

**Given** a stored `document` (or any other memory)
**When** the agent calls `ask(ref_id, question, mode="auto")`
**Then** it receives a short answer plus the mode used and a citation list, produced by `ReasonerPort`; without an external reasoner the built-in fallback returns the top-matching chunks under `mode="rag"`

### US3: RLM Studio adapter and reasoner-backed consolidation (Priority: MEDIUM)

**Given** `rlmstudio` importable in the server's environment
**When** `MEMKERNEL_REASONER=rlmstudio` is set
**Then** `ask` delegates to `rlmstudio.interact(content, question, mode)` with `mode` passed through unchanged (`direct|rag|rlm|auto`), and `consolidate(synthesize=True)` uses the same reasoner to draft long-term statements from a session's short-term memories

### US4: `MemoryLifecycle` component (Priority: HIGH)

**Given** a harness author (haa, or the Claude Code hook scripts)
**When** they instantiate `MemoryLifecycle(build_service())`
**Then** `on_session_start()`, `on_pre_compact(summary)`, `on_post_compact()` and `on_session_end(summary)` perform the whole session protocol and return the text to inject, and the three hook templates become thin wrappers over it

### US5: Release hygiene (Priority: LOW)

**Given** the 0.3 changes are complete
**When** the release is prepared
**Then** the version is `0.3.0`, the CHANGELOG lists the changes, the README documents `document`, `ask` and `MemoryLifecycle`, the MCP tool count stays below ten, and the release workflow's artifact actions target Node 24

## Requirements

- **FR-001**: `core/ports.py` MUST define `DocumentStorePort` with `put(content, name) -> str`, `get(doc_id) -> str | None`, `index(doc_id, chunks) -> int` and `search(doc_id, query, top_k) -> list[str]`, and `ReasonerPort` with `ask(content, question, mode) -> Answer`, where `Answer` is a pydantic model in `core/models.py` with fields `answer`, `mode`, `citations`, `usage`.
- **FR-002**: `MemoryType.DOCUMENT` MUST exist in the long-term tier with default importance 0.6, exported as `document` through the MCP `retain` tool, and MUST be excluded from `WikiExporter` (documents are sources, not wiki pages).
- **FR-003**: `MemoryService.retain(type=DOCUMENT)` MUST store the full body through the configured `DocumentStorePort`, index its chunks (token-based splitter from `retrieval/chunking.py`, not the AST chunker), and keep one memkernel record whose content is the document summary (first 1,000 characters plus a line-count/outline line) with `source=<name>` and metadata `document_id=<doc_id>`.
- **FR-004**: A built-in `LocalDocumentStore` in `storage/documents.py` MUST implement `DocumentStorePort` on top of the existing ChromaDB collection (chunk records tagged `document_chunk`, body kept as a canonical record), so that `document` works with no extra dependency.
- **FR-005**: `MemoryService.ask(ref_id, question, mode="auto")` MUST resolve the memory, load its body (document store for `document`, own content otherwise), call `ReasonerPort.ask`, record an access on the memory, and return the `Answer`; a missing `ref_id` returns `None`.
- **FR-006**: A built-in `LocalReasoner` in `retrieval/reasoner.py` MUST implement `ReasonerPort` without any LLM: it chunks the content, ranks chunks with the existing hybrid search components (dense + BM25 + RRF) against the question, and returns the top chunks joined as `answer` with `mode="rag"` and one citation per chunk.
- **FR-007**: `adapters/rlmstudio.py` MUST implement `ReasonerPort` by importing `rlmstudio` lazily inside the adapter (never at package import time) and calling `rlmstudio.interact(content, question, mode=mode)`; when `rlmstudio` is not importable the adapter MUST raise `ReasonerUnavailable` at construction and `build_service()` MUST fall back to `LocalReasoner` with a logged warning.
- **FR-008**: Settings MUST gain `reasoner: Literal["local", "rlmstudio"] = "local"`, `document_store: Literal["local"] = "local"`, `document_summary_chars: int = 1000`, `ask_top_k: int = 5` (all under the `MEMKERNEL_` prefix) and `build_service()` MUST wire the chosen reasoner and document store.
- **FR-009**: `MemoryService.consolidate(synthesize: bool = False)` MUST, when `synthesize=True` and a non-local reasoner is configured, call `ReasonerPort.ask` once over the concatenated candidate contents with a fixed distillation prompt and add the returned statements to the report under `"suggested"` (list of `{"content", "type"}`); with the local reasoner `suggested` MUST be an empty list and no error.
- **FR-010**: The MCP server MUST expose `ask(ref_id, question, mode="auto")` and MUST NOT expose `forget_expired` any more (purging stays inside `consolidate`), so the registered tool count stays below ten; `MemoryService.forget_expired` stays as a Python method.
- **FR-011**: `memkernel/lifecycle.py` MUST define `MemoryLifecycle(service, settings=None)` with `on_session_start() -> str`, `on_pre_compact(summary: str) -> str`, `on_post_compact() -> str`, `on_session_end(summary: str) -> str`, each returning markdown text suitable for injection and performing exactly what the corresponding hook template does today (checkpoint retain, consolidate, latest checkpoint, long-term context, promotion candidates, wiki pointer).
- **FR-012**: `templates/hooks/session-start.py`, `pre-compact.py` and `post-compact.py` MUST be reduced to building the service and printing the matching `MemoryLifecycle` method's return value; their stdout format MUST stay backward compatible (same section headings).
- **FR-013**: Every new public behaviour MUST have unit tests under `tests/unit/` (ports contract, local document store, local reasoner, ask on document and non-document memories, adapter fallback when `rlmstudio` is absent using a fake module injected into `sys.modules`, lifecycle methods) and one e2e test in `tests/e2e/test_mcp_roundtrip.py` covering `retain(type="document")` → `ask` → `recall(tier="long_term")`; the suite MUST keep coverage at or above 80 percent.
- **FR-014**: `pyproject.toml` version MUST be `0.3.0`, `CHANGELOG.md` MUST gain a `[0.3.0]` section, `README.md` MUST document the `document` type, the `ask` tool, the reasoner settings and `MemoryLifecycle`, and `templates/claude-memory-instructions.md` MUST tell the agent to use `retain(type="document")` plus `ask()` for anything longer than a screen instead of `get()`.
- **FR-015**: `.github/workflows/release.yml` MUST use `actions/upload-artifact@v5` and `actions/download-artifact@v6`; `.github/workflows/ci.yml` MUST stay unchanged otherwise.
- **FR-016**: The code MUST NOT add a runtime dependency; `rlm-studio` MUST NOT be added to `pyproject.toml` dependencies or extras in this release (it is not on PyPI yet); the adapter's import contract is documented in the README with a `pip install "rlm-studio @ git+https://github.com/gosha70/rlm-studio"` note.

## Constraints / What NOT to Build

- No knowledge graph, no Personalized PageRank, no bi-temporal validity intervals — out of scope (ADR-007 alternatives).
- No executable `procedure` skills (Voyager metadata) — roadmap 0.3 lists it, but it is a separate feature with its own sandbox concerns.
- No HTTP client for a running `rlm-studio studio` server — the adapter is in-process only; an HTTP `ReasonerPort` is a later feature.
- No LLM calls inside memkernel itself; the only LLM access is through `ReasonerPort` implementations, and the default is the LLM-free `LocalReasoner`.
- No change to the `retain`/`recall`/`get`/`forget`/`promote`/`consolidate`/`wiki_*` tool signatures beyond the additions named in the requirements.
- No new MCP tools other than `ask`; the ceiling is ten tools (FR-013 of the original spec), and this release stays at nine.
- No edits under `docs/adr/` other than marking ADR-009 `accepted`; design questions go to the owner, not into ADR rewrites.

## Key Entities

- **DocumentStorePort**: protocol for storing and chunk-indexing document bodies; `LocalDocumentStore` is the built-in implementation on ChromaDB.
- **ReasonerPort**: protocol for answering a question about a body of text in a given mode; `LocalReasoner` (no LLM) and `RLMStudioReasoner` (adapter) implement it.
- **Answer**: pydantic model `{answer: str, mode: str, citations: list[str], usage: dict[str, float | int]}` returned by `ask`.
- **document**: a long-term `MemoryType` whose memkernel record is a summary; the body lives in the document store and is reachable through `document_id` metadata.
- **MemoryLifecycle**: the session-protocol component (start, pre-compact, post-compact, end) that hooks and harnesses call instead of re-implementing the protocol.
- **ReasonerUnavailable**: exception raised by an adapter whose backing package is not importable; `build_service()` catches it and falls back.

## Success Criteria

1. US1 is demonstrable: `retain(type="document")` on a 5,000-line text returns a `ref_id`, `get(ref_id)` returns a summary of at most `document_summary_chars + 200` characters, `recall("<a phrase from page 40>")` returns that document, and the chunk records are not returned as separate top-level results.
2. US2 is demonstrable with the local reasoner: `ask(ref_id, "<question answered on page 40>")` returns an `Answer` whose `citations` contain the chunk with the phrase and whose `mode` is `rag`.
3. US3 is demonstrable with a fake `rlmstudio` module: `MEMKERNEL_REASONER=rlmstudio` routes `ask` to `interact` with the exact `mode` string; without the module `build_service()` logs a warning and `ask` still answers through the local reasoner.
4. US4 is demonstrable: running the three hook templates against an ephemeral store prints the same section headings as 0.2.0, and `MemoryLifecycle` has unit tests for all four methods.
5. `poetry run ruff check src/ tests/`, `poetry run ruff format --check src/ tests/`, `poetry run mypy src/` and `poetry run pytest -m "not slow" --cov=memkernel --cov-fail-under=80` all pass; the registered MCP tools are exactly `retain, recall, get, forget, promote, consolidate, ask, wiki_export, wiki_import`.
6. `pyproject.toml` says `0.3.0`, `CHANGELOG.md` has the `[0.3.0]` section, and `release.yml` references `upload-artifact@v5` and `download-artifact@v6`.

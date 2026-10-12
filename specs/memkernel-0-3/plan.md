---
spec_mode: full
feature_id: memkernel-0-3
risk_category: feature
justification: "Four new public surfaces (ports, document type, ask tool, lifecycle component) across core, storage, retrieval, MCP and templates; a full spec keeps the unattended build bounded."
status: approved
date: 2026-10-11
collaboration_mode: single
origin:
  urls:
    - https://github.com/gosha70/memkernel/blob/main/docs/adr/ADR-009-rlm-studio-for-documents.md
    - https://github.com/gosha70/memkernel/blob/main/docs/roadmap.md
    - https://github.com/gosha70/memkernel/blob/main/docs/integration/harness-integration.md
  origin_claim: |
    Continue memkernel on a 0.3 branch: the DocumentStorePort/ReasonerPort
    ports, the document memory type, ask(), MemoryLifecycle, plus the
    two-line artifact-action bump from the release warnings. Implement it
    the fastest, most automated way using code-copilot-team's unattended
    build loop with DeepSeek as the code reviewer. RLM Studio is the
    document layer (owner decision, ADR-009): its Direct / RAG / RLM / auto
    selection is what "hybrid mode" means for memkernel, passed through
    unchanged. haa is the future component-assembly harness, so every
    capability must also exist as a Python component with a small, stable
    interface, not only as an MCP tool.
---

# Implementation Plan: memkernel 0.3 — documents, ask(), lifecycle component

**Branch**: `feature/memkernel-0-3`
**Input**: specs/memkernel-0-3/spec.md

## Summary

memkernel 0.2 stores memories but has no way to hold a large artefact without
loading it into the agent's context. 0.3 adds a `document` memory type backed
by a `DocumentStorePort`, an `ask()` operation backed by a `ReasonerPort`
(LLM-free local fallback; RLM Studio adapter when its package is importable),
and a `MemoryLifecycle` component that packages the session protocol for
hooks and for the haa harness. The release also removes the standalone
`forget_expired` tool to stay under the ten-tool ceiling and bumps the
release workflow's artifact actions.

## Technical Context

**Language/Version**: Python 3.11–3.13, Poetry, pydantic 2, FastMCP (`mcp` 1.x), ChromaDB 1.5
**Primary Dependencies**: `src/memkernel/core/{ports,models,services}.py`, `storage/chroma.py`, `retrieval/{chunking,search,sparse}.py`, `factory.py`, `config.py`, `mcp/tools/memory.py`, `mcp/server.py`, `templates/hooks/*.py`, `wiki/sync.py`
**Testing**: `poetry run pytest -m "not slow" -q -p no:cacheprovider` with `tests/conftest.py::MockEmbedding` and `chromadb.EphemeralClient()`; e2e through `mcp.shared.memory.create_connected_server_and_client_session`
**Constraints**: no new runtime dependency; `rlmstudio` imported lazily only; MCP tool count < 10; 0.2.x stores must load unchanged; coverage ≥ 80 percent; ruff line length 120; mypy strict

## Constitution Check

| Rule file | Concern | Status |
|-----------|---------|--------|
| `coding-standards.md` | No magic strings, no secrets, lint-clean | OK — settings carry defaults; prompts live in module constants |
| `safety.md` | No credentials in source, inputs validated | OK — `ask` validates `mode` against the four known values; no keys |
| `copilot-conventions.md` | One logical change per commit, repo is source of truth | OK — one phase per driver commit |

## Architecture Decisions

### ADR-1: Two ports, both with LLM-free defaults

**Context**: ADR-009 adopts RLM Studio as the document layer, but memkernel must keep working with no extra dependency and no LLM.
**Decision**: `DocumentStorePort` and `ReasonerPort` are protocols in `core/ports.py`; `LocalDocumentStore` (ChromaDB) and `LocalReasoner` (hybrid search over chunks) are the defaults; `RLMStudioReasoner` is opt-in via `MEMKERNEL_REASONER=rlmstudio`.
**Consequences**: `ask` always answers; quality improves when RLM Studio is present. The adapter is tested with a fake module, not the real package.

### ADR-2: Documents reuse the canonical-plus-chunks pattern

**Context**: `code` memories already store a canonical record plus chunk records linked by `chunk_refs`, with `forget` cleaning both.
**Decision**: `document` follows the same pattern through the document store, with a token-based splitter instead of the AST chunker and the canonical record's content replaced by a summary. Chunk records are tagged `document_chunk` and filtered out of top-level `recall` results.
**Consequences**: no schema migration; `forget` works unchanged; `recall` must filter one more tag.

### ADR-3: `forget_expired` leaves the MCP surface

**Context**: `ask` is the tenth tool; the ceiling is ten exclusive.
**Decision**: remove the `forget_expired` tool (consolidate already purges); keep the service method.
**Consequences**: noted in CHANGELOG as a removal in a pre-1.0 release.

### ADR-4: `MemoryLifecycle` returns text, performs no I/O beyond the service

**Context**: haa and the Claude Code hooks both need the session protocol; haa injects text into its message list, hooks print to stdout.
**Decision**: each lifecycle method returns a markdown string and takes only what the service provides; printing and stdin parsing stay in the hook scripts.
**Consequences**: identical behaviour across harnesses; easy to unit test.

## Project Structure

```
src/memkernel/core/ports.py               — DocumentStorePort, ReasonerPort
src/memkernel/core/models.py              — MemoryType.DOCUMENT, Answer, DEFAULT_IMPORTANCE/TYPE_TIER entries
src/memkernel/core/services.py            — retain(DOCUMENT) path, ask(), consolidate(synthesize), chunk filtering
src/memkernel/storage/documents.py        — LocalDocumentStore
src/memkernel/retrieval/reasoner.py       — LocalReasoner (+ ReasonerUnavailable)
src/memkernel/adapters/__init__.py        — package
src/memkernel/adapters/rlmstudio.py       — RLMStudioReasoner (lazy import)
src/memkernel/lifecycle.py                — MemoryLifecycle
src/memkernel/config.py                   — reasoner, document_store, document_summary_chars, ask_top_k
src/memkernel/factory.py                  — wiring + fallback
src/memkernel/mcp/tools/memory.py         — ask tool; forget_expired removed
src/memkernel/wiki/sync.py                — skip DOCUMENT on export
templates/hooks/{session-start,pre-compact,post-compact}.py — thin wrappers
templates/claude-memory-instructions.md   — document + ask guidance
tests/unit/test_documents.py, test_reasoner.py, test_ask.py, test_rlmstudio_adapter.py, test_lifecycle_component.py
tests/e2e/test_mcp_roundtrip.py           — document → ask → recall; tool set updated
README.md, CHANGELOG.md, pyproject.toml   — docs + 0.3.0
.github/workflows/release.yml             — artifact actions v5/v6
docs/adr/ADR-009-rlm-studio-for-documents.md — status: accepted
```

## Scope

### Task 1: Ports, models, settings, local document store (US1)

**Files**: `core/ports.py`, `core/models.py`, `config.py`, `storage/documents.py`, `core/services.py`, `wiki/sync.py`, tests
**Acceptance criteria**:
- [ ] FR-001, FR-002, FR-003, FR-004, FR-008 (settings part) implemented
- [ ] `recall` never returns `document_chunk` records at top level
- [ ] `tests/unit/test_documents.py` covers put/get/index/search, retain(DOCUMENT), summary shape, forget cleanup, wiki export skip

### Task 2: Local reasoner and ask() (US2)

**Files**: `retrieval/reasoner.py`, `core/services.py`, `mcp/tools/memory.py`, `factory.py`, tests
**Acceptance criteria**:
- [ ] FR-005, FR-006, FR-010 implemented; tool set is exactly nine tools
- [ ] `tests/unit/test_reasoner.py`, `tests/unit/test_ask.py`, e2e document → ask → recall

### Task 3: RLM Studio adapter and reasoner-backed consolidation (US3)

**Files**: `adapters/rlmstudio.py`, `factory.py`, `core/services.py`, tests
**Acceptance criteria**:
- [ ] FR-007, FR-009, FR-016 implemented
- [ ] `tests/unit/test_rlmstudio_adapter.py` uses a fake `rlmstudio` in `sys.modules`; fallback path logs a warning and uses `LocalReasoner`

### Task 4: MemoryLifecycle and thin hooks (US4)

**Files**: `lifecycle.py`, `templates/hooks/*.py`, tests
**Acceptance criteria**:
- [ ] FR-011, FR-012 implemented; hook stdout headings unchanged from 0.2.0
- [ ] `tests/unit/test_lifecycle_component.py` covers all four methods

### Task 5: Release hygiene (US5)

**Files**: `pyproject.toml`, `src/memkernel/__init__.py`, `CHANGELOG.md`, `README.md`, `templates/claude-memory-instructions.md`, `.github/workflows/release.yml`, `docs/adr/ADR-009-rlm-studio-for-documents.md`
**Acceptance criteria**:
- [ ] FR-013 (coverage), FR-014, FR-015 satisfied
- [ ] Full fast suite, ruff, ruff format, mypy green

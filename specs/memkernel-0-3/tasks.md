# Tasks: memkernel 0.3 — documents, ask(), lifecycle component

<!-- One `## US<n>:` group = one auto-build phase. [US#] tags trace to spec.md. -->
<!-- Run per phase: poetry run ruff check src/ tests/ && poetry run ruff format --check src/ tests/ && poetry run mypy src/ && poetry run pytest -m "not slow" -q -p no:cacheprovider -->

## US1: Ports and the `document` memory type

| # | [P] | Task | File(s) | Owner | Done |
|---|-----|------|---------|-------|------|
| 1 | | Add `DocumentStorePort` and `ReasonerPort` protocols (FR-001); keep them under `@runtime_checkable` like the existing ports | `src/memkernel/core/ports.py` | build | [x] |
| 2 | [P] | Add `Answer` model and `MemoryType.DOCUMENT` (long-term, importance 0.6) to `TYPE_TIER` / `DEFAULT_IMPORTANCE` (FR-001, FR-002) | `src/memkernel/core/models.py` | build | [x] |
| 3 | [P] | Add settings `reasoner`, `document_store`, `document_summary_chars`, `ask_top_k` (FR-008) and document them in `README.md`'s configuration table | `src/memkernel/config.py`, `README.md` | build | [x] |
| 4 | | Implement `LocalDocumentStore` on the existing Chroma collection: body as canonical record, chunks tagged `document_chunk` with `document_id`, `put/get/index/search` (FR-004); add a token-based `split_text` helper if `retrieval/chunking.py` lacks a public one | `src/memkernel/storage/documents.py`, `src/memkernel/retrieval/chunking.py` | build | [x] |
| 5 | | Wire `retain(type=DOCUMENT)`: store body via the port, index chunks, keep a summary record with `document_id` metadata; hide `document_chunk` records from `recall` and `list_memories`; `forget` removes body and chunks (FR-003) | `src/memkernel/core/services.py`, `src/memkernel/storage/chroma.py` | build | [x] |
| 6 | [P] | Skip `DOCUMENT` in `WikiExporter` (FR-002) and add a test | `src/memkernel/wiki/sync.py`, `tests/unit/test_wiki.py` | build | [x] |
| 7 | | Unit tests for the store and the retain path (FR-013) | `tests/unit/test_documents.py` | build | [x] |

**Checkpoint US1** — verify before continuing:
- [x] `poetry run mypy src/` clean; `poetry run ruff check src/ tests/` clean
- [x] `poetry run pytest tests/unit/test_documents.py tests/unit/test_wiki.py -q` green
- [x] Existing 0.2 tests still pass unchanged

---

## US2: `ask()` with the LLM-free local reasoner

| # | [P] | Task | File(s) | Owner | Done |
|---|-----|------|---------|-------|------|
| 8 | | Implement `LocalReasoner` (FR-006): chunk, rank with dense + BM25 + RRF via the existing components, return top `ask_top_k` chunks as `Answer(mode="rag")`; define `ReasonerUnavailable` here | `src/memkernel/retrieval/reasoner.py` | build | [x] |
| 9 | | Add `MemoryService.ask(ref_id, question, mode)` (FR-005): resolve body (document store for `document`, own content otherwise), validate `mode` ∈ {direct, rag, rlm, auto}, touch the memory, return `Answer`; `None` when missing | `src/memkernel/core/services.py` | build | [x] |
| 10 | | Wire `reasoner` and `document_store` in `build_service()` (FR-008) with the local defaults | `src/memkernel/factory.py` | build | [x] |
| 11 | | Register the `ask` MCP tool and remove the `forget_expired` tool (FR-010); update the tool-set e2e assertion and add the document → ask → recall e2e test | `src/memkernel/mcp/tools/memory.py`, `tests/e2e/test_mcp_roundtrip.py` | build | [x] |
| 12 | [P] | Unit tests for the reasoner and `ask` on document and non-document memories (FR-013) | `tests/unit/test_reasoner.py`, `tests/unit/test_ask.py` | build | [x] |

**Checkpoint US2** — verify before continuing:
- [x] `tests/e2e/test_mcp_roundtrip.py` passes with exactly nine tools listed
- [x] `poetry run pytest -m "not slow" -q` green; mypy and ruff clean

---

## US3: RLM Studio adapter and reasoner-backed consolidation

| # | [P] | Task | File(s) | Owner | Done |
|---|-----|------|---------|-------|------|
| 13 | | Implement `RLMStudioReasoner` (FR-007): lazy `import rlmstudio` inside `__init__`, raise `ReasonerUnavailable` if absent, `ask` calls `rlmstudio.interact(content, question, mode=mode)` and maps the result into `Answer` (answer text, mode actually used, usage tokens/cost when present) | `src/memkernel/adapters/__init__.py`, `src/memkernel/adapters/rlmstudio.py` | build | [ ] |
| 14 | | `build_service()`: when `settings.reasoner == "rlmstudio"`, construct the adapter, catch `ReasonerUnavailable`, log a warning, fall back to `LocalReasoner` (FR-007) | `src/memkernel/factory.py` | build | [ ] |
| 15 | | `consolidate(synthesize=True)` (FR-009): one `ReasonerPort.ask` call over candidate contents with a module-constant distillation prompt; parse one statement per line into `suggested: [{content, type}]`; local reasoner yields `[]` | `src/memkernel/core/services.py`, `src/memkernel/mcp/tools/memory.py` | build | [ ] |
| 16 | [P] | Tests with a fake `rlmstudio` module injected via `monkeypatch.setitem(sys.modules, ...)`: mode pass-through, result mapping, fallback warning, `synthesize=True` parsing (FR-013, FR-016) | `tests/unit/test_rlmstudio_adapter.py` | build | [ ] |

**Checkpoint US3** — verify before continuing:
- [ ] `pyproject.toml` dependencies unchanged (FR-016); `poetry check --lock` passes
- [ ] `poetry run pytest -m "not slow" -q` green; mypy and ruff clean

---

## US4: `MemoryLifecycle` component and thin hooks

| # | [P] | Task | File(s) | Owner | Done |
|---|-----|------|---------|-------|------|
| 17 | | Implement `MemoryLifecycle` with `on_session_start`, `on_pre_compact(summary)`, `on_post_compact`, `on_session_end(summary)` returning the markdown the hooks print today (FR-011) | `src/memkernel/lifecycle.py` | build | [ ] |
| 18 | | Rewrite the three hook templates as thin wrappers: build service, call the method, print; keep stdin handling in `pre-compact.py` and the section headings byte-identical (FR-012) | `templates/hooks/session-start.py`, `templates/hooks/pre-compact.py`, `templates/hooks/post-compact.py` | build | [ ] |
| 19 | [P] | Unit tests for all four methods against an ephemeral store with `MockEmbedding` (FR-013) | `tests/unit/test_lifecycle_component.py` | build | [ ] |

**Checkpoint US4** — verify before continuing:
- [ ] Each hook template compiles (`python -m py_compile`) and `ruff check templates/` is clean
- [ ] `poetry run pytest -m "not slow" -q` green; mypy clean

---

## US5: Release hygiene

| # | [P] | Task | File(s) | Owner | Done |
|---|-----|------|---------|-------|------|
| 20 | | Bump to `0.3.0`; write the `[0.3.0]` CHANGELOG section (added: document, ask, ports, lifecycle, reasoner settings; removed: `forget_expired` tool) (FR-014) | `pyproject.toml`, `src/memkernel/__init__.py`, `CHANGELOG.md` | build | [ ] |
| 21 | [P] | README: `document` type row, `ask` tool row, reasoner/document settings, `MemoryLifecycle` embedding example, `rlm-studio` git-install note; CLAUDE.md template: `document` + `ask` guidance (FR-014, FR-016) | `README.md`, `templates/claude-memory-instructions.md` | build | [ ] |
| 22 | [P] | Bump `actions/upload-artifact@v5` and `actions/download-artifact@v6` in the release workflow (FR-015); mark ADR-009 `accepted` | `.github/workflows/release.yml`, `docs/adr/ADR-009-rlm-studio-for-documents.md` | build | [ ] |

**Checkpoint US5** — verify before continuing:
- [ ] `poetry build` succeeds and the wheel installs in a clean venv
- [ ] Coverage ≥ 80 percent: `poetry run pytest -m "not slow" --cov=memkernel --cov-fail-under=80 -q`

---

## Final Verification

- [ ] Type checker: 0 errors
- [ ] Linter: 0 errors
- [ ] All existing tests pass
- [ ] No [NEEDS CLARIFICATION] markers remain in spec.md
- [ ] Registered MCP tools are exactly: retain, recall, get, forget, promote, consolidate, ask, wiki_export, wiki_import

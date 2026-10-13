# memkernel — project instructions

Code-aware memory server for AI coding copilots: an MCP server plus a Python
library (`memkernel.factory.build_service()`). Tiered memory (working /
short-term / long-term), hybrid search (dense + BM25 + RRF), AST chunking,
consolidation, an LLM-wiki bridge. Design docs live in `docs/`; the current
feature spec lives in `specs/<feature-id>/` (spec-driven development, one
`## US<n>:` group in `tasks.md` per build phase).

## Commands

```bash
poetry install                                  # once
poetry run pytest -m "not slow" -q -p no:cacheprovider   # fast suite (what CI gates on)
poetry run pytest -q                            # full suite; the 4 slow tests download a model
poetry run ruff check src/ tests/ && poetry run ruff format --check src/ tests/
poetry run mypy src/                            # strict
poetry run pytest -m "not slow" --cov=memkernel --cov-fail-under=80 -q
poetry build                                    # wheel + sdist
```

Format with `poetry run ruff format src/ tests/` before finishing. Templates
under `templates/` are linted too (`poetry run ruff check templates/`).

## Layout

```
src/memkernel/core/      models (MemoryTier, MemoryType, Memory, ArtifactRef), ports (Protocols), services (MemoryService)
src/memkernel/storage/   ChromaDB adapter (VectorStorePort)
src/memkernel/retrieval/ AST chunker, sentence-transformers embedding, BM25, HybridSearchService + rescore
src/memkernel/memory/    lifecycle (decay, retention), TTL policies, dedup
src/memkernel/wiki/      LLM-wiki bridge (export drafts, import pages)
src/memkernel/mcp/       FastMCP server + tools; src/memkernel/api/ FastAPI admin
src/memkernel/factory.py build_service() — the supported embedding entry point
templates/               CLAUDE.md snippet, Claude Code hook scripts (session-start, pre/post-compact), kiro/ (mcp.json, steering, hooks)
tests/unit, tests/e2e    unit tests use chromadb.EphemeralClient() + tests/conftest.py MockEmbedding;
                         e2e uses mcp.shared.memory.create_connected_server_and_client_session
```

## Conventions that CI enforces

- Python 3.11–3.13; `from __future__ import annotations`; type hints everywhere (mypy strict, pydantic plugin).
- Ruff: line length 120, rule sets E/F/W/I/N/UP/B/A/SIM/TCH. Imports used only for typing go under `if TYPE_CHECKING:`.
- Every source file starts with the two-line header `# Copyright (c) 2026 EGOGE` / `# SPDX-License-Identifier: Apache-2.0`.
- `core/` depends only on the Protocols in `core/ports.py`, never on concrete adapters; new backends are adapters behind a port.
- No new runtime dependencies without a decision record in `docs/adr/`; optional integrations import their package lazily and degrade with a logged warning.
- ChromaDB metadata is scalar only: lists are stored as comma-separated strings (see `_split_csv` in `storage/chroma.py`); new metadata keys must load with a default so 0.1.x/0.2.x stores keep working.
- MCP tool count must stay below ten (`tests/e2e/test_mcp_roundtrip.py::test_tool_count_under_10` pins the exact set).
- Coverage ≥ 80 percent on the fast suite; `core/ports.py` is excluded.
- Settings are pydantic-settings fields with the `MEMKERNEL_` prefix; document every new one in the README configuration table.
- Memories are never edited in place by callers: a replacement is a new record with `supersedes=<old ref_id>`.

## Working rules

- Read `docs/architecture/memory-tiers.md` and the relevant ADR before changing scoring, tiers, or ports.
- Keep each change to one phase of `specs/<feature-id>/tasks.md`; do not edit `specs/` except artifacts the phase owns.
- Do not commit, push, or change branches inside an auto-build session; the driver owns git.
- Update `CHANGELOG.md` under `[Unreleased]` for user-visible changes; bump `pyproject.toml` and `src/memkernel/__init__.py` together.
- Report test failures and skipped steps plainly; never skip or weaken a test to get green.

## Memory (optional)

If the `memkernel` MCP server is configured for this session, read
`~/.claude/skills/memkernel-memory/SKILL.md` and follow it (recall at start,
checkpoint before compaction, promote what proved useful).

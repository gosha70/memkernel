# Tasks: memkernel 0.7, Release B part 2c: governed mode and curation debt (#48)

<!-- One `## US<n>:` group = one build phase. Build on the owner's go after the spec merges. -->

## US1: Governed mode, curation debt, export batches and source revisions

| # | [P] | Task | File(s) | Owner | Done |
|---|-----|------|---------|-------|------|
| 1 | | `MEMKERNEL_WIKI_MODE`, the governed preflight on export and import, `ungated` never touching wiki-studio; `mode` and `configured_mode` (FR-001) | `src/memkernel/config.py`, `src/memkernel/wiki/studio.py`, `src/memkernel/wiki/sync.py`, `src/memkernel/mcp/tools/wiki.py` | build | [x] |
| 2 | | Curation debt section: preflight, kind order, lent budget, read-only ledger snapshot and the in-memory ledger lock, the time bound by a child process (FR-002) | `src/memkernel/lifecycle.py`, `src/memkernel/wiki/studio.py`, `src/memkernel/wiki/ledger.py` | build | [x] |
| 3 | | Export batch and `remaining`; `sha:` and `memkernel_sha256`; `assign_page_ids` (FR-003 to FR-005) | `src/memkernel/config.py`, `src/memkernel/wiki/sync.py`, `src/memkernel/wiki/studio.py` | build | [x] |
| 4 | | Tests SC-1 to SC-5 against the real wiki-studio | `tests/integration/test_wiki_governed_mode.py`, `tests/unit/test_lifecycle*.py`, `tests/unit/test_wiki.py` | build | [x] |
| 5 | | README (settings, lock file, `hash_recipe`), CHANGELOG (FR-006, FR-007) | docs | build | [x] |
| 6 | | Gates: fast suite green, coverage >= 80 percent, ruff and mypy clean (SC-6) | — | build | [x] |

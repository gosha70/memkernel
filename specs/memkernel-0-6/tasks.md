# Tasks: memkernel 0.6 — the Release B wiki bridge

<!-- One `## US<n>:` group = one build phase. Part 1 merges only after memkernel's v0.5.0 tag. -->

## US1: Snapshot removal and the combined gate (part 1, wiki-studio 0.6.0)

| # | [P] | Task | File(s) | Owner | Done |
|---|-----|------|---------|-------|------|
| 1 | | Remove `_WikiSnapshot` and its take/restore; report gate failures as `gate_error` without restoring (FR-001) | `src/memkernel/wiki/sync.py`, `tests/unit/test_wiki_studio.py` | build | [ ] |
| 2 | | Scaffold a missing index/log through `api.init` on the gated path; direct writer unchanged (FR-002) | `src/memkernel/wiki/sync.py`, `src/memkernel/wiki/studio.py`, tests | build | [ ] |
| 3 | | Extra floor `wiki-studio >=0.6.0,<1`; `gate_available()` refuses older or `init`-less installs; ADR-010 addendum; dev lock 0.6.0 (FR-003, FR-004) | `pyproject.toml`, `poetry.lock`, `src/memkernel/wiki/studio.py`, `docs/adr/ADR-010-wiki-studio-as-wiki-maintainer.md` | build | [ ] |
| 4 | | Integration tests against the real wiki-studio: compatibility (SC-1), concurrency (SC-2), forced failure (SC-3), old version refused (SC-4), archive step failed (SC-6) | `tests/integration/test_wiki_studio_gate.py` | build | [ ] |

## US2: Receipt reference and documentation (part 1)

| # | [P] | Task | File(s) | Owner | Done |
|---|-----|------|---------|-------|------|
| 5 | | `ExportReport.proposal`, `submission_digest`, `archived_dir` from the receipt where it actually is; `archive_hint` (also logged) when not archived; `receipt_error` when unreadable; the same keys and an updated description in the `wiki_export` response (FR-005, FR-008) | `src/memkernel/wiki/sync.py`, `src/memkernel/wiki/studio.py`, `src/memkernel/mcp/tools/wiki.py`, tests | build | [ ] |
| 6 | | README: lock-file ignore note; CHANGELOG `[Unreleased]`: snapshot removal and the scaffold left after a failed export, wiki-studio's scaffold for a new wiki (`stable`, different titles), floor 0.6.0, each new `wiki_export` response key (FR-001, FR-002, FR-006, FR-007, FR-008) | `README.md`, `CHANGELOG.md` | build | [ ] |
| 7 | | Committed, then failed: detect a commit from the receipt's `post_sha256` (content fallback), report it as written with the finishing hint; README, CHANGELOG (FR-009, SC-7) | `src/memkernel/wiki/studio.py`, `src/memkernel/wiki/sync.py`, tests, `README.md`, `CHANGELOG.md` | build | [ ] |

## US3: Approved-only import (part 2a, wiki-studio 0.7.0)
| # | Dep | Task | Files | Agent | Done |
|---|-----|------|-------|-------|------|
| 8 | | Floor 0.7.0 for both paths: extra, dev dependency, lock, `GATE_MIN_VERSION`, required calls incl. `review_state` and `read_page`; ADR-010 note (FR-003, FR-004) | `pyproject.toml`, `poetry.lock`, `src/memkernel/wiki/studio.py`, `docs/adr/ADR-010-wiki-studio-as-wiki-maintainer.md`, tests | build | [ ] |
| 9 | 8 | Governed import through `review_state` + `read_page` sha check; ungoverned without the extra; `import_error` below the floor; identity tags and idempotency; stale keeps its memory (FR-010–FR-013) | `src/memkernel/wiki/sync.py`, `src/memkernel/wiki/studio.py`, tests | build | [ ] |

## US4: `corrects` reconciliation (part 2a)
| # | Dep | Task | Files | Agent | Done |
|---|-----|------|-------|-------|------|
| 10 | 9 | `corrects` grammar parser and its tests (incl. wiki-studio's multi-corrections fixture); `MemoryService.supersede` (FR-017; read and update memory-tiers.md first); reconciliation with `unresolved` and `invalid_corrects` (FR-014, FR-015, FR-017) | `src/memkernel/wiki/sync.py`, `src/memkernel/core/services.py`, `docs/architecture/memory-tiers.md`, tests | build | [ ] |
| 11 | 10 | `ImportReport` fields and the `wiki_import` response and description; README (governed vs ungoverned import, `corrects`), CHANGELOG; run wiki-studio's Release B loop test and record it (FR-016, SC-8, SC-9) | `src/memkernel/wiki/sync.py`, `src/memkernel/mcp/tools/wiki.py`, `README.md`, `CHANGELOG.md`, tests | build | [ ] |

## Part 2b and 2c — to be specified
2b: withdrawal on supersession, deprecation and deletion, with a per-page sync state and a retry path.
2c: governed configuration (refuse the ungated writer, check the manifest policy) and curation debt at session start.

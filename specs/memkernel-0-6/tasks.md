# Tasks: memkernel 0.6 — the Release B wiki bridge

<!-- One `## US<n>:` group = one build phase. Part 1 merges only after memkernel's v0.5.0 tag. -->

## US1: Snapshot removal and the combined gate (part 1, wiki-studio 0.6.0)

| # | [P] | Task | File(s) | Owner | Done |
|---|-----|------|---------|-------|------|
| 1 | | Remove `_WikiSnapshot` and its take/restore; report gate failures as `gate_error` without restoring (FR-001) | `src/memkernel/wiki/sync.py`, `tests/unit/test_wiki_studio.py` | build | [x] |
| 2 | | Scaffold a missing index/log through `api.init` on the gated path; direct writer unchanged (FR-002) | `src/memkernel/wiki/sync.py`, `src/memkernel/wiki/studio.py`, tests | build | [x] |
| 3 | | Extra floor `wiki-studio >=0.6.0,<1`; `gate_available()` refuses older or `init`-less installs; ADR-010 addendum; dev lock 0.6.0 (FR-003, FR-004) | `pyproject.toml`, `poetry.lock`, `src/memkernel/wiki/studio.py`, `docs/adr/ADR-010-wiki-studio-as-wiki-maintainer.md` | build | [x] |
| 4 | | Integration tests against the real wiki-studio: compatibility (SC-1), concurrency (SC-2), forced failure (SC-3), old version refused (SC-4), archive step failed (SC-6) | `tests/integration/test_wiki_studio_gate.py` | build | [x] |

## US2: Receipt reference and documentation (part 1)

| # | [P] | Task | File(s) | Owner | Done |
|---|-----|------|---------|-------|------|
| 5 | | `ExportReport.proposal`, `submission_digest`, `archived_dir` from the receipt where it actually is; `archive_hint` (also logged) when not archived; `receipt_error` when unreadable; the same keys and an updated description in the `wiki_export` response (FR-005, FR-008) | `src/memkernel/wiki/sync.py`, `src/memkernel/wiki/studio.py`, `src/memkernel/mcp/tools/wiki.py`, tests | build | [x] |
| 6 | | README: lock-file ignore note; CHANGELOG `[Unreleased]`: snapshot removal and the scaffold left after a failed export, wiki-studio's scaffold for a new wiki (`stable`, different titles), floor 0.6.0, each new `wiki_export` response key (FR-001, FR-002, FR-006, FR-007, FR-008) | `README.md`, `CHANGELOG.md` | build | [x] |

## US3+: Part 2 (needs wiki-studio 0.7.0) — to be specified
Approved-only import via `api.review_state`; `corrects` key and grammar with a round-trip fixture; withdrawal
and reconciliation; governed configuration. Shaped once 0.7.0's API is published.

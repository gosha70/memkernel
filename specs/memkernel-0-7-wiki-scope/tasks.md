# Tasks: scope the wiki import to its own wiki (#80)

<!-- One `## US<n>:` group = one build phase. Build on the owner's go after the spec merges, and after the memkernel-0-7-store-locks build. -->

## US1: Identity, scoped dedup and adoption

| # | [P] | Task | File(s) | Owner | Done |
|---|-----|------|---------|-------|------|
| 1 | | `MemoryService.set_wiki_identity`; `AmbiguousDedupError`; identity writes through `merge_tags` (store-locks spec), reserved identity tags in `retain` and the MCP tool, `promote` dropping every wiki-import tag, `retain(wiki_identity=)` (FR-008); `retain(..., dedup_owner=)` and ordinary retain never deduping onto identity-tagged records (FR-002, FR-005, FR-009; read memory-tiers.md first) | `src/memkernel/core/services.py`, `src/memkernel/mcp/tools/memory.py` | build | [ ] |
| 2 | | Identity: both tags, membership, identity validation on both paths, the identity changes, the conflict check and the ledger migration, all before any write (FR-001) | `src/memkernel/wiki/sync.py`, `src/memkernel/wiki/ledger.py`, `src/memkernel/wiki/studio.py` | build | [ ] |
| 3 | | Scoped `_previous`, D4, D5 and `_is_this_pages`; owned candidates first, supersession recovery, duplicate detection in the import, D4 and D5 (FR-003a); the import under `exclusive("wiki-import")` (FR-008); `adopt_legacy`, `adopt_pages`, `adopt_manifest` and sole-candidate adoption, else `ambiguous`; scoped rebuild (FR-003, FR-004, FR-006) | `src/memkernel/wiki/sync.py`, `src/memkernel/mcp/tools/wiki.py` | build | [ ] |
| 4 | | Tests SC-1 to SC-5, SC-7 and SC-8 (SC-8 with real processes) against the real wiki-studio, the ungoverned path and the core methods | `tests/integration/test_wiki_scope.py`, `tests/unit/test_services.py`, `tests/unit/test_wiki.py` | build | [ ] |
| 5 | | README, memory-tiers.md, CHANGELOG (FR-007) | docs | build | [ ] |
| 6 | | Gates: fast suite green, coverage ≥ 80 percent, ruff and mypy clean (SC-6) | — | build | [ ] |

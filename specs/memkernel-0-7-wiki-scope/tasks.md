# Tasks: scope the wiki import to its own wiki (#80)

<!-- One `## US<n>:` group = one build phase. Build on the owner's go after the spec merges. -->

## US1: The wiki tag, the scope and adoption

| # | [P] | Task | File(s) | Owner | Done |
|---|-----|------|---------|-------|------|
| 1 | | The wiki key on both paths (api.info, or the manifest file read directly; unreadable stops the import); the `wiki:` tag on every retained or current memory (FR-001) | `src/memkernel/wiki/sync.py`, `src/memkernel/wiki/ledger.py` | build | [ ] |
| 2 | | Scoped `live` lists; legacy adoption; the scoped rebuild (FR-002 to FR-004) | `src/memkernel/wiki/sync.py` | build | [ ] |
| 3 | | Tests SC-1 to SC-4 against the real wiki-studio, and the ungoverned path | `tests/integration/test_wiki_scope.py`, `tests/unit/test_wiki.py` | build | [ ] |
| 4 | | README and CHANGELOG (FR-005) | `README.md`, `CHANGELOG.md` | build | [ ] |

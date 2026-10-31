# Spec: scope the wiki import to its own wiki (#80)

Origin: #80 and the owner's go of 2026-10-31 (`origin/2026-10-31-issue-80.md`). Facts are in `plan.md`.

## User Scenarios
- **US1:** a project imports two wikis into one store, and pages in both share relative paths or `page_id`s.
  Importing, deprecating or superseding a page in one wiki never touches the other wiki's memories.
- **US2:** a project with one wiki and a store written by 0.6 upgrades. Its next import behaves as before: the
  existing memories are recognised, not duplicated, and from then on they carry their wiki.

## Decisions (recommendations for the owner to confirm)
**S1. Record the wiki on each imported memory (#80 option A).**
- Every memory the import retains, or finds already current, carries the tag `wiki:<wiki key>`.
- The key is the sync ledger's (`ledger.wiki_key`): the manifest's `wiki_id`, else the sha256 of the wiki
  directory's path relative to the project root.
- Both imports derive it the same way:
  - the governed import from `api.info`, as #78 does;
  - the ungoverned import by reading `<wiki>/.wiki-studio.json`'s `wiki_id` directly. No wiki-studio is needed.
- An existing manifest that cannot be read stops the import with `import_error` on both paths, as #78 does for the
  governed one, so a wiki never switches keys silently.
- **Rejected, B:** storing `source` relative to the project root. It changes an existing field's meaning, and
  every old memory would need a path migration.
- **Rejected, C:** scoping by the ledger only. Legacy memories would never match, which breaks re-importing a 0.6
  store, and the ungoverned import has no ledger.

**S2. Which memories are a page's previous memory.**
- `_previous`, in the import, deprecation (D5) and supersession (D4), considers only live wiki memories that
  carry **this** wiki's `wiki:` tag, plus **legacy** memories that carry no `wiki:` tag at all.
- A memory tagged with another wiki's key is never a candidate.

**S3. Legacy memories are adopted on first match.**
- When a legacy memory is matched as a page's previous memory, the import adopts it into this wiki:
  - **already current:** the page is retained again with the same content and `dedup_source`. That is a dedup
    hit, which merges the new tags, `wiki:` included, into the existing record, as a frontmatter-only revision
    already does today.
  - **a new revision:** the new record carries the `wiki:` tag and supersedes the legacy one, as today.
- After one import of each wiki, its memories are tagged.
- **The one residual case**, stated in the CHANGELOG: a 0.6 store that already holds two wikis' memories at
  overlapping paths cannot tell which wiki a legacy memory came from. The first wiki imported after the upgrade
  adopts it. A project with one wiki, the documented setup, is unaffected.

**S4. The ledger's rebuild follows the scope.** A corrupt ledger is rebuilt (#78) only from memories tagged with
this wiki, or legacy ones, never from another wiki's.

## Requirements
- **FR-001 (S1):**
  - The tag `wiki:<wiki key>` is added to every memory either import retains or finds already current.
  - The key comes from `ledger.wiki_key`, with the manifest's `wiki_id` read by `api.info` (governed) or from
    `<wiki>/.wiki-studio.json` (ungoverned).
  - A present but unreadable manifest gives `import_error` on both paths.
  - The tag uses `_tag_safe`.
- **FR-002 (S2):** both `live` lists exclude memories tagged with another wiki's key. `_previous` is otherwise
  unchanged: key, then source; and the shared-record rule of memkernel-0-6 FR-012.
- **FR-003 (S3):** a matched legacy memory is adopted as S3 describes. An adopted memory is reported as today
  (`unchanged` or `imported`), and nothing new is added to the report.
- **FR-004 (S4):** `WikiImporter._rebuild` uses the scoped list.
- **FR-005:** README (the wiki tag, the residual 0.6 case) and CHANGELOG `[Unreleased]`.

## Constraints / What NOT to Build
- No change to the export, the ledger's file name or key, deletion (D3), or the MCP tools.
- No migration pass over the store. Adoption happens at import.
- Release B 2c is a separate spec.

## Key Entities
- **`wiki:<wiki key>` tag:** the wiki an imported memory belongs to. Absent on legacy memories (0.6 and earlier).

## Success Criteria
- **SC-1 (US1):** with two wikis sharing a page path:
  - importing B never supersedes A's memory;
  - deprecating or superseding B's page never withdraws or supersedes A's memory;
  - each memory carries its own wiki's tag;
  - the same holds for a shared `page_id`.
- **SC-2 (US2):**
  - A legacy memory, with no `wiki:` tag, is matched by its wiki's next import and adopted: unchanged pages
    report `unchanged`, and the record gains the tag without a new record.
  - A changed page supersedes it with a tagged record.
- **SC-3 (S1):**
  - The ungoverned import uses the manifest file's `wiki_id`, the same key the governed import uses for the same
    wiki.
  - A wiki without a manifest uses the path-hash key.
  - An unreadable manifest stops both imports with `import_error`.
- **SC-4 (S4):** a corrupt ledger's rebuild ignores another wiki's memories.
- **SC-5:** fast suite green, coverage ≥ 80 percent, ruff and mypy clean.

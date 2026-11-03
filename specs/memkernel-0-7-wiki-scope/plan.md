---
spec_mode: full
feature_id: memkernel-0-7-wiki-scope
risk_category: bugfix
justification: "Changes which memories the wiki import treats as a page's previous memory (supersession, deprecation and withdrawal all depend on it), adds a tag to every imported memory, and must keep stores written by 0.6 working: the import's identity rule and a cross-version contract, so a full spec."
status: draft
date: 2026-10-31
collaboration_mode: single
origin:
  issue: gosha70/memkernel#80
  urls:
    - https://github.com/gosha70/memkernel/issues/80
  transcripts:
    - specs/memkernel-0-7-wiki-scope/origin/2026-10-31-issue-80.md
    - specs/memkernel-0-7-wiki-scope/origin/2026-10-31-review-84.md
    - specs/memkernel-0-7-wiki-scope/origin/2026-10-31-review-84-2.md
    - specs/memkernel-0-7-wiki-scope/origin/2026-10-31-deepseek-84.md
    - specs/memkernel-0-7-wiki-scope/origin/2026-11-03-review-84-3.md
    - specs/memkernel-0-7-wiki-scope/origin/2026-11-03-review-84-4.md
    - specs/memkernel-0-7-wiki-scope/origin/2026-11-03-review-84-5.md
    - specs/memkernel-0-7-wiki-scope/origin/2026-11-03-review-84-6-windows.md
    - specs/memkernel-0-7-wiki-scope/origin/2026-11-03-split-s8.md
    - specs/memkernel-0-7-wiki-scope/origin/2026-11-03-windows-dedup.md
    - specs/memkernel-0-7-wiki-scope/origin/2026-11-03-adopt-legacy.md
  origin_claim: |
    #80: wiki_import matches a page's previous memory across wikis, so importing
    wiki B can supersede, deprecate or withdraw wiki A's memory at the same
    relative path or page_id. The owner's go (2026-10-31) to spec it, #80 before
    Release B 2c, with option A (record the wiki on each imported memory) as the
    recommendation made when the issue was offered.
---

# Plan: scope the wiki import to its own wiki (#80)

## Facts (checked 2026-10-31, `main` `a1a5b32`)
- **The defect:**
  - `WikiImporter._previous` (`src/memkernel/wiki/sync.py:652`) matches a page's live memory by `page_key:` tag, else by `source`. Both values are wiki-relative.
  - The candidates come from every live wiki memory in the project: the governed import's `live` (line 384) and the withdrawal pass's `live` (line 455). The ungoverned import uses the same list (line 386).
  - Reproduced: importing wiki B's page at A's path superseded A's memory (#80).
- **Tags:** an imported memory today gets `wiki`, `page:<slug>`, `page_type:<type>`, and with governance `page_key:<key>` and `page_sha:<sha>` (line 619). Nothing names the wiki.
- **The wiki key** already exists for the sync ledger (`memkernel.wiki.ledger.wiki_key`): the manifest's `wiki_id`, else the sha256 of the wiki directory's path relative to the project root.
  - The governed import reads `wiki_id` through `api.info`, and stops on an unreadable manifest (#78).
  - The manifest is the file `<wiki>/.wiki-studio.json` (wiki-studio `contract.py:146-147`, `paths.py:71`, key `wiki_id`), so the ungoverned import can read it without wiki-studio.
- **Deletion (D3)** is already per wiki, through the ledger. It is not part of this defect.

## Files (for the build)
- `src/memkernel/core/services.py` (`set_wiki_identity`, `retain(dedup_owner=)`), `src/memkernel/wiki/sync.py`,
  `ledger.py`, `studio.py`, `mcp/tools/wiki.py`, `mcp/tools/memory.py` (reserved identity tags), tests, README, `memory-tiers.md` and CHANGELOG.

## Checked after the review of `1499944`
- `find_by_hash` returns the first live match by content, type and source (`storage/chroma.py:277`), so identical
  pages at one path share one record across wikis.
- `_retain_page` returns before any retain for a revision that is already current.
- `_is_this_pages` matches by page key or path only (`sync.py:645-649`).
- wiki-studio's `parse_manifest` checks: a UTF-8 JSON object, `manifest_version` ≤ 1, the schema id and version, a
  UUID `wiki_id`, the fingerprint, the policy and `created_by`; the file is opened without following symlinks
  (`contract.py:120, 160-245`).

## Checked after the second review (of the uncommitted revision over `1499944`)
- The ungoverned import keeps no ledger (`sync.py:385-386`): ledger evidence exists only on the governed path, so
  S6 relies on identity tags on both paths and on the ledger only for the governed migration.
- A 0.6 memory carries `wiki`, `page:`, `page_type:` and, governed, `page_key:` and `page_sha:`; nothing in it
  names its wiki, so no store-side evidence can prove ownership (S4).
- An existing corrupt ledger is reported as `ledger_error` and the import continues (`sync.py:399-401`); S6's
  migration errors are therefore a separate, fatal `import_error`.

## Checked after the third review (2026-11-03)
- `MemoryService.retain` returns `str` (`services.py:258-271`), so two dedup hits need a typed error to reach the
  report.
- `_retain_page` resolves `_previous` and returns early for a current revision before calling `retain`
  (`sync.py:604-630`), so duplicate detection belongs in the importer, ahead of both.
- `_previous` looks up by page key, then by path (`sync.py:652-668`); S3's owned-first order keeps that lookup.
- The importer class is `WikiImporter` (`sync.py:363`); the ledger takes one `fcntl` lock per ledger file
  (`ledger.py:100-111`).

## Checked after the third review's corrected pass (2026-11-03)
- `retain` writes the replacement, then calls `_mark_superseded` (`services.py:623-626`); the replacement's
  metadata carries `supersedes` (`_new_metadata`), and `supersede(ref_id, by_ref)` completes a partial mark
  without overwriting a marker (`services.py:465-505`): the recovery data and the recovery call exist.
- `update_metadata` fetches, merges and writes the whole metadata with no lock (`chroma.py:301-320`);
  `_refresh_existing` writes `tags` computed from a record read before the call (`services.py:676-688`); a
  `get`/`recall` touch writes metadata from the MCP server's process.
- The ungoverned import takes no lock; the governed one holds only its own wiki's ledger lock (`sync.py:385-403`).
- D4 looks up the predecessor and successor, D5 the deprecated page, all with `_previous` (`sync.py:472-526`).

## Checked after the fourth review (2026-11-03)
- The store is selected by `chroma_persist_path` and the collection `<prefix>_<project_id>` (`chroma.py:165-176`);
  `state_dir` is a separate setting (`config.py:34-39`).
- Without `fcntl`, the store-open lock and the ledger lock run unlocked (`chroma.py:31-34, 60-65`;
  `ledger.py:27-30`).
- `ChromaVectorStore(settings, client=...)` accepts a caller's client, so two adapters can wrap one
  `EphemeralClient` (`chroma.py:160-176`).
- The MCP `retain` tool accepts any `tags` (`mcp/tools/memory.py:24-33`); `promote` copies the source's tags into
  the new record (`services.py:1055-1064`).
- chromadb 1.5.9 (`pyproject.toml`: `>=1.0,<2`): `collection.update(metadatas=[{"n": 2}])` kept the existing
  `tags` key, so metadata updates merge keys natively.

## Checked after the fifth review (2026-11-03)
- chromadb 1.5.9: two `EphemeralClient()` objects are distinct but share one `_system`, and a record added
  through one is counted through the other.
- `client.get_settings()` gives `is_persistent` and `persist_directory`; clients expose `tenant` and `database`
  (`default_tenant`, `default_database` for both kinds).
- The `update_metadata` port contract accepts any keys (`core/ports.py:52-54`).
- CI runs on `ubuntu-latest` only (`.github/workflows/ci.yml`), so no Windows lock test can run there.

## After the split (2026-11-03)
The store locks and the single tag writer moved to `specs/memkernel-0-7-store-locks/` (the owner's "split S8").
The facts above about `update_metadata`, lock identity and clients now back that spec; this one keeps the wiki
part of S8 and depends on it.

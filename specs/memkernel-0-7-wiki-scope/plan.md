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
- `src/memkernel/wiki/sync.py` (and `ledger.py` for the shared key), tests, README and CHANGELOG.

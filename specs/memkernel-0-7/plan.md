---
spec_mode: full
feature_id: memkernel-0-7
risk_category: feature
justification: "Adds a liveness rule to core (a new metadata marker read by every live-record path), a new public MemoryService method, a per-project sync ledger in the store directory, and changes what the governed wiki import does with deleted, deprecated and superseded pages; several modules and a cross-project contract, so a full spec."
status: draft
date: 2026-10-30
collaboration_mode: single
origin:
  issue: gosha70/memkernel#48
  urls:
    - https://github.com/gosha70/memkernel/issues/48
    - https://github.com/gosha70/wiki-studio/issues/38
    - https://github.com/gosha70/wiki-studio/blob/main/specs/pitches/38-release-b-governed-curation/pitch.md
  transcripts:
    - specs/memkernel-0-7/origin/2026-10-30-part-2b.md
    - specs/memkernel-0-7/origin/2026-10-30-review-76.md
  origin_claim: |
    Release B part 2b for #48: "Withdrawal on supersession, deprecation and explicit
    deletion; a pending / applied / failed synchronisation state with a retry path; no
    claimed transaction across Markdown and the memory store." The owner's go
    (2026-10-30): spec in a new specs/memkernel-0-7/ directory; check wiki-studio 0.7.0
    and 0.8.0 for deletion and deprecation signals first; weigh "withdraw" as a new
    marker vs a tombstone record, and sync state as tags vs a ledger in memkernel's
    store directory; recommendations for the owner to confirm; spec-only PR.
---

# Plan: memkernel 0.7, Release B part 2b: withdrawal and sync state

## What wiki-studio tells a consumer (checked 2026-10-30)
Checked in wiki-studio 0.7.0, which is installed, and in the 0.8.0 sdist from PyPI, uploaded 2026-10-29. `review.py`, `proposal.py` and `findings.py` are byte-identical between the two; 0.8.0 only adds capabilities. All citations are to 0.7.0.
- **Supersession is a review state.** `api.review_state` reports `superseded` (reason `superseded_by`) when a page's frontmatter has `superseded_by: <wiki-relative path>` (`review.py:175-177`, `719-750`).
  - `ReviewState` does not name the successor; the consumer reads it from the page's frontmatter.
  - Lint requires the successor to exist, not to be the page itself, and not to be superseded in turn (`lint.py:251`, `358-364`).
- **Deprecation is not a state.** It is only the frontmatter value `status: deprecated` (`schema/page-types.md:16`). An approved deprecated page reads `approved`, and `approve` does not check it (`promoter.py:2156-2168`). The consumer parses `status` from `read_page`'s text.
- **Deletion has no signal.**
  - There is no `delete` action (`proposal.py:80`, in both versions), and the Release B pitch rules out `move` and `delete` actions.
  - Receipts cannot express a deletion.
  - No findings kind covers it, and no API lists pages that existed and are gone.
  - `review_state(pages=None)` lists every regular `*.md` under the wiki except `index.md`, `log.md`, `schema/`, `scripts/` and `.audit/` (`review.py:685-688`, `lint.py:57`, `90-103`). A deleted page simply stops appearing.
  - Approval records under `.audit/approvals/` outlive the page, but there is no API that lists them.
- **Renames:** a page keeps its key only through a well-formed `page_id`. Without one, the old path disappears and the new path reads `unapproved` (pitch lines 382-390).
- **The pitch** assigns withdrawal and the sync state to memkernel. "Mapping review states to memory tiers, withdrawal and `Memory.superseded_by` is memkernel's decision" (pitch lines 598-601, 649-650).

So memkernel detects deletion itself. 2b needs no new wiki-studio API, and the floor stays at 0.7.0.

## The two choices the owner asked to weigh
See spec "Decisions for the owner". The recommendations are:
- **Withdrawal:** a new `withdrawn` marker (option A), not a tombstone record (B) or a sentinel in `superseded_by` (C).
- **Sync state:** a ledger file per project and wiki in a memkernel state directory outside Chroma's, not tags on the page's memory.

Confirmed by the owner on 2026-10-30, with D3 changed: only memories this wiki's ledger recorded may be withdrawn as deleted.

## Files (for the build, after the spec is approved)
- `src/memkernel/core/models.py` and `src/memkernel/storage/chroma.py`: the marker, loaded with a default.
- `src/memkernel/core/services.py`: `withdraw()` and one liveness predicate used at every live-record site.
- `src/memkernel/config.py`: `MEMKERNEL_STATE_DIR`.
- `src/memkernel/wiki/sync.py` and a new `src/memkernel/wiki/ledger.py`: withdrawal and the ledger.
- `src/memkernel/mcp/tools/wiki.py`: the response keys.
- `docs/architecture/memory-tiers.md`, `README.md`, `CHANGELOG.md`.
- Tests.

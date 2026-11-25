# Spec: hide a wiki page's source memory while the page's memory is shown (#164, #59 S5)

Status: draft, for the owner's review. The owner's decisions of 2026-11-25 are fixed (O1–O7); D1–D6 are proposed.
S5 leaves #59 open: the owner closes it. Order (O7): this spec's PR, then #90's build, then S5's build.

## What memkernel does today (`main` at `3ba5c72`)

| #164 | Today | Gap |
|---|---|---|
| A page exported from a memory, approved and imported | Export writes `memkernel_ref`, `memkernel_sha256` and `memkernel_hash_scheme` on the draft (`src/memkernel/wiki/sync.py:403-406`). Import retains the page as a new `wiki` memory and reads only `corrects:` (`sync.py:843`). | A page approved without `corrects:` leaves its source live beside it: recall and the hook blocks can show the same fact twice (#59 D8). |
| Promoted chains | The hook blocks drop a live source of a promoted memory (`src/memkernel/lifecycle.py:487-488`, `_distinct`); promotion candidates leave out a source with a visible promoted copy (`src/memkernel/core/services.py:1558`). MCP `recall` does neither. | `_distinct` computes the sources from all candidates (up to `HOOK_CANDIDATES`, 10) and only then keeps the first 5: a promoted copy ranked 6th–10th hides its source while the copy itself is not shown. |
| wiki-studio | ADR-0002 registers `corrects` as memkernel-owned and kept byte for byte. `memkernel_ref`, `memkernel_sha256` and `memkernel_hash_scheme` are not registered; wiki-studio keeps them today because `api.propose` writes a caller's bytes unchanged. | S5 makes memkernel read `memkernel_ref` at import, so it carries meaning, as `corrects` does. |

## User Scenarios

- **US1:** An agent's decision is exported, a curator approves the page unchanged, and the next import brings it back.
  The page's memory is now linked to its source.
- **US2:** The session hook or `recall` finds both the page's memory and its source, and shows only the page's.
  `get(source)` still returns the source.
- **US3:** A page whose `memkernel_ref` doesn't hold up (the memory is gone, retired, private, or its hash differs) is
  imported as before, with no link, and the import report says why.

## Requirements

- **FR-001 The link (O2, O3, O4).** When the import retains a page (D6), the page's memory is linked to the memory
  its `memkernel_ref` names only if all of these hold:
  1. The page has `memkernel_ref` (otherwise no link and nothing reported, O3).
  2. The page has no `corrects` key, valid or not (O4: `corrects` wins). A page with `corrects` is a correction:
     what it supersedes is decided by `corrects` alone, as today.
  3. The named memory is in this store and is not a `wiki` memory.
  4. The named memory is live: not superseded or withdrawn (`Memory.retired()` is false).
  5. The named memory's scope is `project`.
  6. `compute_content_hash(named.content, scheme)` equals the page's `memkernel_sha256`, where `scheme` is the page's
     `memkernel_hash_scheme`, or `sha256-raw` when the key is absent (pages exported before 0.17). A page without
     `memkernel_sha256`, or with a scheme memkernel doesn't know, gets no link.
- **FR-002 Where the link lives (D1).** The link is a reserved tag `wiki-source:<ref_id>` on the page's memory, written
  only by the import. A new record gets it through `retain`; an existing record (a page imported before S5, or a
  revision that changed only frontmatter, which `retain` deduplicates) through an import-only service method, as
  `set_wiki_identity` does for the identity tags. Each import sets the tag to what FR-001 decides now: it adds it,
  replaces a stale one, or removes it. `retain` raises `ValueError` for a caller-supplied tag with this prefix, as it
  does for `wiki-path:` and `wiki-id:`, so no caller can hide another memory. `promote` drops it from the copy, as it
  drops the other import tags (`services.py:1502`). A page memory that is later superseded or withdrawn keeps its tag
  but hides nothing, since it is never shown.
- **FR-003 Hiding (O1, D2).** A memory's **ancestors** are the memories reached from it by following `promoted_from`
  and `wiki-source:` links, repeatedly (a promoted copy of a page reaches the page and the page's source). A memory is
  hidden only when one of its descendants is shown in the same block or result. Never both: if the page's memory is
  dropped (flagged, expired, out of scope, outside the window, cut by the limit), the source can appear. Nothing is
  superseded, withdrawn or edited in the source; `get`, `list_memories`, health and the context diff see it as before.
  - **The selection.** One pass over the candidates in rank order: skip a candidate that is already hidden; otherwise
    keep it, hide its ancestors, and remove any of them already kept; stop at the limit. The pass visits each
    candidate once, so it ends, and the rank order fixes the result. Because hiding follows ancestors transitively, a
    kept item removed later is an ancestor of a later kept item, so everything it hid stays hidden by a shown item.
    Ancestors are followed through the store, with a visited set, so a link to a record outside the candidates still
    counts.
  - **Hook blocks:** `_distinct` uses the selection for both promoted and imported links, which also fixes the
    6th–10th case in the table above.
  - **MCP `recall`:** per D2, the selection over `recall`'s filtered fetch window (which widens until it has `top_k`
    live results), with `top_k` as the limit. A page memory outside the window hides nothing. Each hidden source counts
    once under `collapsed`, however many shown memories descend from it.
- **FR-004 Promotion candidates (D3).** A source linked from a live page memory is not a promotion candidate.
- **FR-005 The report (D5).** `ImportReport` gains `linked` (`{"page", "ref_id"}`) and `unlinked`
  (`{"page", "ref_id", "reason"}`). The reasons, one per refused condition of FR-001: `has_corrects`, `not_in_store`,
  `wiki_memory`, `retired`, `not_project_scope`, `no_hash`, `unknown_scheme`, `hash_mismatch`. The MCP `wiki_import`
  result carries both lists. Two pages may link the same source; each is reported.
- **FR-006 Docs.** README (the wiki section: what the link does and when it is refused) and CHANGELOG under
  `[Unreleased]`.

## Constraints / What NOT to Build

- No supersede on import (O1), no new MCP tool, setting, record type or dependency; the tool count is unchanged.
- No change to export: the three keys it writes are already there.
- No change to `corrects` handling.
- No relevance floor, per-prompt recall, per-session injected list or hook latency (#164 out of scope; latency is
  Phase 4, O6).
- No wiki-studio change in this slice (D4 is a separate wiki-studio issue, on the owner's go).

## Decisions (owner, 2026-11-25)

- **O1** Hide the source; don't supersede it.
- **O2** Link only when the named memory is live, in the project scope, and its hash matches the page's
  `memkernel_sha256` under `memkernel_hash_scheme`.
- **O3** A page without `memkernel_ref` gets no link.
- **O4** `corrects` wins over `memkernel_ref`.
- **O5** The spec says whether a hidden source stays a promotion candidate (D3), and whether wiki-studio's ADR-0002
  should register `memkernel_ref` (D4).
- **O6** Hook latency goes to Phase 4.
- **O7** Order: S5's spec PR, then #90's build, then S5's build.

## Decisions (proposed)

- **D1 A reserved tag.** Recommended: `wiki-source:<ref_id>`. Tags are already how the import marks its records, they
  load with a default on older stores (no tag, no link), and the import already updates its own records' tags in
  place through `set_wiki_identity`. A new metadata field would need its own update path for the frontmatter-only
  revisions that `retain` deduplicates.
- **D2 Where `recall` hides.** Options:
  (a) hook blocks only, as promotion works today;
  (b) hook blocks and `recall`, imported links only;
  (c) hook blocks and `recall`, imported and promoted links.
  Recommended: **(c)**. #59's item is "recall collapses promoted and imported chains", and both checks sit where
  `recall` already applies its supersede link fallback (`services.py:1150`, `1202`). A source hidden this way is
  counted in the receipt's `excluded` under a new reason, `collapsed`. (c) changes `recall` for promoted chains too,
  which no earlier slice did; (b) keeps that out of S5, and differs in the build only in following `wiki-source:`
  links alone inside `recall`.
- **D3 Promotion candidates.** Recommended: **not a candidate**, as with a promoted source (`services.py:1558-1563`).
  The page is reviewed knowledge already, and promoting the source would put a long-term copy beside the page. In
  practice this changes little: `wiki_export` drafts only long-term memories (`sync.py:258`), which are never
  candidates (`services.py:1562`). It matters only for a library caller that passes short-term memories to
  `WikiExporter.export(memories=...)`.
- **D4 wiki-studio's ADR-0002.** Recommended: **yes**, register `memkernel_ref`, `memkernel_sha256` and
  `memkernel_hash_scheme` as memkernel-owned keys kept byte for byte and not interpreted, as `corrects` is. After S5
  memkernel reads all three at import, and today they survive only because `api.propose` writes a caller's bytes
  unchanged; a later wiki-studio change could drop or rewrite them and silently turn the link off. The ADR is
  wiki-studio's file (it says memkernel does not write it), so this is a wiki-studio issue, filed on the owner's go.
  S5's build does not wait for it.
- **D5 Report the link.** Recommended: `linked` and `unlinked` as in FR-005, so a curator can see why a page's source
  is still shown. A page without `memkernel_ref` reports nothing (O3).
- **D6 Which imports link.** Recommended: **only the governed path** (approved revisions through wiki-studio). The
  ungoverned path imports drafts too, and an exported draft is the exporter's own copy with placeholder sections
  (`sync.py:383-388`): hiding the source behind it would show the agent less.

## Success Criteria

- **SC-1 (US1, US2).** Export a decision, approve the page unchanged, import: the page's memory carries the link; the
  startup hook block and `recall` (per D2) show the page's memory and not the source; `get(source)` returns it
  unchanged.
- **SC-2 (US3).** Each refused case yields no link and its reason in `unlinked`: `corrects` present (valid and
  invalid), not in the store, a `wiki` memory, superseded, withdrawn, agent or task scope, hash mismatch, no
  `memkernel_sha256`, an unknown scheme. A page without `memkernel_ref` gets no link and no report entry. A page
  exported before 0.17 (no `memkernel_hash_scheme`) links under `sha256-raw`.
- **SC-3 Never both.** With the page's memory flagged, expired, outside the window or ranked past the limit, the
  source is shown. Also covered: the promoted-copy case past the hook limit; a chain (a promoted copy of a page hides
  the page and its source); two pages linking one source (counted once); a source ranked above its page (removed when
  the page is kept, and the slot refilled).
- **SC-4 Reserved tag.** `retain` with a `wiki-source:` tag raises `ValueError`.
- **SC-5 Re-import.** A page imported before S5 gains the link on the next import; a frontmatter-only revision that
  adds `corrects`, or one that removes `memkernel_ref`, drops it.
- **SC-6 Candidates (D3)** and the receipt's `collapsed` count (D2).
- **SC-7** The fast suite, ruff, `mypy --strict` and coverage gates pass; README and CHANGELOG updated.

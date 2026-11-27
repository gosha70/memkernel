# Origin alignment check — memkernel-0-18-imported-page-collapse, build

Origin: #164, #59's Phase 2 item and finding D8, and the owner's messages of 2026-11-25 recorded in
origin/2026-11-25-issue-164.md, with the decisions O1–O7, D1–D6 (D2 as option (c)), Q1 and the visibility addition.

Origin claim: as in plan.md.

Working claim (the build): the governed import links an approved page's memory to the memory its `memkernel_ref`
names, by the reserved tag `wiki-source:`, only when FR-001's checks pass, and reports `linked` and `unlinked`;
`recall` and the hook blocks run one selection over what they show, following `promoted_from` and `wiki-source:`
through records the caller can see; receipts count and list what was hidden; a source linked from a live page is not
a promotion candidate.

Choices the plan did not state, each tied to a requirement:
  - **`recall(..., collapse=False)`.** The recall-based hook blocks (compact recovery, `on_post_compact`) fetch 10
    candidates with `recall` and show 5. If `recall` selected at 10, a descendant ranked 6th–10th would hide an
    ancestor the block could show, which the owner's invariant forbids ("If a descendant is ranked sixth and only five
    results are shown, it must not suppress an otherwise visible ancestor"). So these blocks ask `recall` for the
    filtered window unselected and select once, at their own limit. The MCP `recall` tool always selects.
  - **The link is written by `set_wiki_source` on every import, new records included.** FR-002 says a new record
    gets the tag through `retain`; the build sets it after `retain` for new and existing records alike, through the
    one import-only method. The outcome FR-002 requires holds: only the import writes the tag, `retain` refuses it
    from callers, and each import sets it to what FR-001 decides now. A failure between the two writes leaves the page
    unlinked until the next import, which links it (the page is then `unchanged` and still checked).
  - **`ancestor_paths` returns each ancestor with its path** rather than the set the plan names, since the receipts'
    `path` needs it.
  - **`eval/anti-rot-128/calibrate.py`** calls the hook selection; it now calls the lifecycle's `_distinct` and asks
    `recall` for the unselected window, as the hook does.

Mismatches:
  - none against the origin.

Verdict: aligned
Confidence: high

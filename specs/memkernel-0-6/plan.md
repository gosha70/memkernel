---
spec_mode: full
feature_id: memkernel-0-6
risk_category: feature
justification: "Changes the wiki bridge's write path (removes the whole-wiki rollback), the optional extra's version floor and the dev lock, and adds integration tests against wiki-studio; later parts change import eligibility. Several files and a cross-project contract, so a full spec."
status: draft
date: 2026-10-26
collaboration_mode: single
origin:
  issue: gosha70/memkernel#48
  urls:
    - https://github.com/gosha70/memkernel/issues/48
    - https://github.com/gosha70/wiki-studio/issues/38
    - https://github.com/gosha70/wiki-studio/blob/main/specs/pitches/38-release-b-governed-curation/pitch.md
  transcripts:
    - specs/memkernel-0-6/origin/2026-10-26-release-b-start.md
    - specs/memkernel-0-6/origin/2026-10-27-committed-then-failed.md
  origin_claim: |
    Close the memkernel side of wiki-studio's Release B (memkernel #48): remove the
    bridge's whole-wiki snapshot and rollback and scaffold through wiki-studio's
    api.init (owner decision 2026-10-24/25), pass the combined integration gate,
    then import approved revisions only and reconcile corrected memories once
    wiki-studio 0.7.0 provides review state. The owner asked on 2026-10-26 to start
    now because it holds wiki-studio's Release B loop job red.
---

# Plan: memkernel 0.6 — the Release B wiki bridge

## Why now, and the constraint
wiki-studio's "memkernel Release B loop" CI job is red (non-blocking, `continue-on-error`) until memkernel #48
lands. memkernel `main` is frozen at 641a508 (0.5.0rc1) until the `v0.5.0` tag (FR-017 of memkernel-0-5):
nothing outside `check_freeze.py`'s allowlist may merge before then. This feature is therefore built on
branches and merged only after the tag.

## Approach
Two parts, because part of Release B needs a wiki-studio release that does not exist yet:
- **Part 1 (US1–US2, buildable now against wiki-studio 0.6.0):** remove `_WikiSnapshot`, scaffold through
  `api.init`, require wiki-studio ≥ 0.6.0 for the gate, record each export's proposal receipt, and pass the
  combined gate's compatibility and concurrency tests.
- **Part 2 (US3+, needs wiki-studio 0.7.0):** approved-only import through `api.review_state`, the `corrects`
  key and its grammar, withdrawal and reconciliation, governed configuration. Shaped in a later amendment of
  this spec once 0.7.0's API is published.

The tests target the bridge's API surface (`propose`, `promote`, `init`, `read_page`), which wiki-studio keeps
unchanged for the bridge in 0.7.0 (owner decision 1, memkernel #48 comment of 2026-10-24); moving the dev lock
from 0.6.0 to 0.7.0 when it is published should need no test change.

## Files (part 1)
`src/memkernel/wiki/sync.py`, `src/memkernel/wiki/studio.py`, `pyproject.toml`, `poetry.lock`,
`docs/adr/ADR-010-wiki-studio-as-wiki-maintainer.md` (addendum), `README.md` (wiki section), `CHANGELOG.md`,
`tests/unit/test_wiki_studio.py`, a new `tests/integration/test_wiki_studio_gate.py`.

## Risks
- Without the snapshot, a failed gated export relies on wiki-studio's own rollback and receipts. That is only
  safe from 0.6.0 on, hence the floor and the refusal of older versions (FR-003).
- A new wiki scaffolded by `api.init` differs from memkernel's direct-writer scaffold, so memkernel-0-5's SC-2
  byte-identity no longer holds for the scaffold of a new wiki (FR-002); pages and appended lines stay identical.
  A failed export now leaves that scaffold in place (FR-001). Both are user-visible and go in the CHANGELOG.
- wiki-studio 0.6.0 can commit an export and fail to archive it; the receipt then stays in the proposals
  directory. FR-005 reads it there and reports "promoted, not archived" (SC-6).

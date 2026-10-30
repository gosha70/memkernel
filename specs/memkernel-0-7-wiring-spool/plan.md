---
spec_mode: full
feature_id: memkernel-0-7-wiring-spool
risk_category: bugfix
justification: "Two small follow-ups in one spec, as the owner asked: the lc-wiki wiring check (an eval artefact whose 0.5 version is pinned by sha256 in released records) and the session spool's pruning (memkernel-0-7-hooks). Several files and a pinned release artefact, so a full spec, kept short."
status: draft
date: 2026-10-30
collaboration_mode: single
origin:
  issue: gosha70/memkernel#81
  urls:
    - https://github.com/gosha70/memkernel/issues/81
    - https://github.com/gosha70/memkernel/pull/79#issuecomment-6529951075
  transcripts:
    - specs/memkernel-0-7-wiring-spool/origin/2026-10-30-go.md
  origin_claim: |
    #81: the lc-wiki wiring check fails wherever wiki-studio >= 0.7 is installed,
    because it imports a draft that the governed import refuses. #79's follow-up:
    a session with a started line but no ended line is never pruned from the
    spool. The owner's go (2026-10-30): "go: spec for #81 (recommend option C,
    both paths) and the spool-pruning follow-up, together, as one small spec-only
    PR for the reviewer."
---

# Plan: the wiring check on both import paths, and spool pruning

## Facts (checked 2026-10-30, `main` `5142bbf`)
- **The wiring check:**
  - `eval/lifecycle-suite/wiring/wiring_check.py` exports a page as a draft and imports it straight away (lines 178–183, 220, 228).
  - The image's memkernel venv is built with `poetry export --only main`, without the `wiki` extra, so its import is ungoverned and the check passes there.
  - The dev venv has wiki-studio 0.7.0, so its import is governed, the draft is refused, and the check fails (#81).
- **"wiki-studio absent":** `memkernel.wiki.studio.load_studio` treats only a `ModuleNotFoundError` whose `name` is `wiki_studio` as absence (`studio.py:85-91`).
- **The pinned 0.5 version:** `calibration/RECORD-2026-10-24.md:156-157` and `report-0.5.0.md:295` pin `wiring_check.py` at sha256 `84ee9444…`, at the commits they name.
- **The spool:** `session_spool.drain` keeps every session that has no `ended` line (`session_spool.py`, `drain`). So a session that never recorded an end, after a crash or with SessionEnd not registered, stays forever (#79 comment).

## Files (for the build)
- `eval/lifecycle-suite/wiring/wiring_check.py` and `tests/unit/test_wiring_check.py` (part A).
- `src/memkernel/session_spool.py`, `src/memkernel/lifecycle.py`, the tests, README and CHANGELOG (part B).

# Origin alignment check — memkernel-0-7, after the review of #76

Origin: as in the previous record, plus specs/memkernel-0-7/origin/2026-10-30-review-76.md.

Origin claim:
> Confirm D1 (state whether a withdrawn record can be superseded and vice versa), D2 (ledger per project and wiki, outside Chroma's directory in a memkernel state dir, lock held for the whole run), D4 (what superseded_by names; unknown successors pending and reported), D5 (once the deprecated revision is approved). Change D3: only memories this wiki's ledger recorded may be withdrawn as deleted; legacy memories never are.

Working claim:
> D1: a withdrawn record can be superseded later (both markers kept); a superseded record is not withdrawn (False, no change); neither marker is cleared or overwritten. D2: one ledger per project and wiki under MEMKERNEL_STATE_DIR (default <project_root>/.memkernel/state), outside Chroma's directory, lock held for the whole import run. D3: only memories with an applied ledger import entry may be withdrawn as deleted; legacy memories never. D4: superseded_by names a wiki-relative page path, resolved through the complete listing; unknown successors stay pending and are reported. D5: withdrawal once the deprecated revision is approved; until then the page is stale and its memory stays live. FR-004, SC-1 to SC-4 and tasks 5-6 follow.

Mismatches:
  - none. Each review point is applied as worded.

Verdict: aligned
Confidence: high

# Origin alignment check — memkernel-0-18-imported-page-collapse, draft

Origin: #164 (S5 of #59), #59's Phase 2 item "recall collapses promoted and imported chains" and finding D8 ("wiki
import doesn't supersede its source"), and the owner's messages of 2026-11-25 recorded in
origin/2026-11-25-issue-164.md.

Origin claim: as in plan.md.

Working claim:
> On the governed import, a page whose memkernel_ref names a live, project-scope, non-wiki memory whose content hashes
> to the page's memkernel_sha256 under memkernel_hash_scheme (sha256-raw when absent), and which has no corrects key,
> links its memory to that source through a reserved tag. The source is hidden only where the linked page memory is
> shown (hook blocks; recall per D2), never superseded or edited, and is not a promotion candidate (D3). The import
> reports linked and unlinked pages. ADR-0002 registration is recommended as a wiki-studio issue (D4). Hook latency
> is left to Phase 4.

Mismatches:
  - none against O1–O7. Two proposals go beyond #164's text and are flagged for the owner: D2 (c) also changes
    recall for promoted chains, and FR-003 fixes the hook blocks' promoted-chain rule past the limit. D6 links on the
    governed path only, which #164 does not say. D1–D6 await the owner.

Verdict: aligned (pending the owner's decisions)
Confidence: medium

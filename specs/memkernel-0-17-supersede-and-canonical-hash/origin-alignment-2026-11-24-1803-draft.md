# Origin alignment check — memkernel-0-17-supersede-and-canonical-hash, draft

Origin: #153 (S4 of #59), #59's Phase 2 plan and finding D8, and the owner's decisions recorded in
origin/2026-11-24-issue-153.md (file S4 with the hashing caveat; the order; H3's A8/C2 on schemes).

Origin claim: as in plan.md.

Working claim:
> Supersede suggestions at retain (decision, convention, fact, procedure; same type, visible, allowed by H2's
> supersede rule; at most 3 above a calibrated threshold; never automatic) and canonical hashing (NFC, LF, no
> trailing spaces, no leading or trailing blank lines; scheme sha256-canonical-v1; records state their scheme; no
> migration: dedup matches either scheme; every comparison within a record's scheme, including revalidation,
> receipts and the context diff, which reports a scheme change as rehashed).

Mismatches:
  - none. The spec states the new scheme's name and how existing records are handled (D6), as #153 requires, and
    the context diff compares within one scheme (FR-003), as #153 and H3's C2 require. D1–D3, D5, D6 await the owner.

Verdict: aligned (pending the owner's decisions)
Confidence: medium

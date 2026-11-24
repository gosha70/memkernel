# Origin alignment check — memkernel-0-15-harness-foundations, the H3 build

Origin: #119 Part 2 (Reproducible Knowledge Context), the reviews the owner passed on, and the owner's decisions: D1–D6
(2026-11-19), amendments H1 and H2 (2026-11-23), amendment H3 with C1 refined and C2–C4 confirmed, then the owner's
fixes (2026-11-24, PR #157).

Origin claim: as in plan.md. Part 2: versioned, inspectable knowledge selections; traceability to sources and source
revisions; awareness of changed, stale, missing or superseded knowledge; an explainable record of why knowledge was
selected. Success scenario: after source code or architectural decisions change, the system can identify differences
from the context used by an earlier harness run.

Working claim:
> Built as amendment H3 says: eval/context-diff/diff.py reads a run's receipts (H1) and reports, per memory, missing,
> superseded, withdrawn, changed, rehashed, flagged (against the receipt's state), source changed (a gone file
> included), unknown or unchanged, with C3's combination rules; each memory judged by the last receipt with its hash;
> code chunks judged by their file record; a note for cut-short ref_ids; exit codes 0, 1, 2; no memory content; in
> CI's strict type check. Tested, starting with SC-2.

Mismatches:
  - none for H3. Noted, unchanged by H3: Part 2's "explainable record of why particular knowledge was selected" is
    served by what the receipt records (the query, its filters, the exclusion counts), as the approved spec decided
    (FR-003, D3); no per-memory reason is recorded.

Verdict: aligned
Confidence: high

# Origin alignment check — memkernel-0-5 (compaction-call tokens in the receipts, FR-018)

Origin: https://github.com/gosha70/memkernel/issues/17 (direction update posted 2026-10-18, issuecomment-6255377037), and the owner's statements in specs/memkernel-0-5/origin/ (2026-10-15 decisions, 2026-10-16 option B, 2026-10-17 wiki_studio arm, 2026-10-18 wiki-studio 0.4.1).

Origin claim:
> Show strong evidence of how memkernel helps with memory and context management, and state clearly what it is and what it is not (it is not a token optimizer). Adopt wiki-studio as the wiki maintainer where the current release is sufficient (lint and health, shared schema) and specify what wiki-studio must expose for the rest (promote gate, schema as code). Finalize the positioning and the wiki-studio contract before the first benchmark run; let the #17 protocol proceed in parallel.

Working claim:
> The first calibration (eval/lifecycle-suite/calibration/RECORD.md) showed that the receipts undercount the compaction calls: each `/compact` step reports 0 tokens while its `compact_boundary` event records a real model call (`pre_tokens` 35,999–37,220), so the receipts miss 460,434 input and 19,268 output tokens against the Console. FR-018 now adds one receipt field, `compaction_tokens_estimate`, the sum of `compact_boundary.pre_tokens`: an estimate of the compaction calls' input only, never added into the token classes or billed totals, shown beside them in the report. The receipt schema moves to version 2 and only version 2 is accepted. It changes what the receipts record, not what the agent, the tasks or the arms do; the recalibration that follows is the first run with it.

Mismatches:
  - none. Per-arm, per-group token usage is what FR-015 asks calibration to measure for the budget; the field makes the compaction share of it visible per session instead of only as a workspace total in the Console.

Verdict: aligned
Confidence: high

Notes:
  - Supersedes origin-alignment-2026-10-19-0100.md.

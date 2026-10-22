# Origin alignment check — memkernel-0-5 (compaction-call tokens in the receipts, FR-018; missing estimates counted)

Origin: https://github.com/gosha70/memkernel/issues/17 (direction update posted 2026-10-18, issuecomment-6255377037), and the owner's statements in specs/memkernel-0-5/origin/ (2026-10-15 decisions, 2026-10-16 option B, 2026-10-17 wiki_studio arm, 2026-10-18 wiki-studio 0.4.1).

Origin claim:
> Show strong evidence of how memkernel helps with memory and context management, and state clearly what it is and what it is not (it is not a token optimizer). Adopt wiki-studio as the wiki maintainer where the current release is sufficient (lint and health, shared schema) and specify what wiki-studio must expose for the rest (promote gate, schema as code). Finalize the positioning and the wiki-studio contract before the first benchmark run; let the #17 protocol proceed in parallel.

Working claim:
> As in origin-alignment-2026-10-20-1200.md: FR-018 adds `compaction_tokens_estimate`, the sum of `compact_boundary.pre_tokens`, an estimate of the compaction calls' input only, kept out of the token classes and billed totals, with receipts at `schema_version: 2` only. Review of the implementation added `compaction_estimates_missing`: the number of compactions whose `pre_tokens` is missing or malformed. Without it, one valid compaction would hide another that reported nothing, and the estimate would fall back to the old undercount unseen; the report now warns whenever it is above zero. It changes what the receipts record, not what the agent, the tasks or the arms do.

Mismatches:
  - none. The field keeps the per-session compaction share of the budget honest; it adds no measurement and changes no arm.

Verdict: aligned
Confidence: high

Notes:
  - Supersedes origin-alignment-2026-10-20-1200.md.

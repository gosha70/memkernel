# Origin alignment check — memkernel-0-5 (FR-016 labels: the test's direction and the mean's sign must agree)

Origin: https://github.com/gosha70/memkernel/issues/17 (direction update posted 2026-10-18, issuecomment-6255377037), and the owner's statements in specs/memkernel-0-5/origin/ (2026-10-15 decisions, 2026-10-16 option B, 2026-10-17 wiki_studio arm, 2026-10-18 wiki-studio 0.4.1, 2026-10-24 measured-run design).

Origin claim:
> Show strong evidence of how memkernel helps with memory and context management, and state clearly what it is and what it is not (it is not a token optimizer). Adopt wiki-studio as the wiki maintainer where the current release is sufficient (lint and health, shared schema) and specify what wiki-studio must expose for the rest (promote gate, schema as code). Finalize the positioning and the wiki-studio contract before the first benchmark run; let the #17 protocol proceed in parallel.

Working claim:
> FR-016 labelled a primary comparison gain or loss from a rejecting sign test and the sign of the mean effect. The two measure different things (how many tasks favour an arm, and by how much), so they can disagree: 16 tasks at +1/5 and 4 at -1 reject in memkernel's favour (Holm p 0.0236) with a mean of -0.04, which the old rule called a loss. A gain now needs the test to reject, more non-tied tasks to favour memkernel, and a positive mean; a loss the reverse; a rejection whose direction and mean disagree, or whose mean is exactly zero, is no detectable difference and the report says the two disagree. Effects are exact fractions, so no label depends on rounding. The design the owner approved on 2026-10-24 is otherwise unchanged.

Mismatches:
  - none. Strong evidence needs a label that cannot call a result a loss when most tasks favour memkernel, or a gain when the mean says otherwise.

Verdict: aligned
Confidence: high

Notes:
  - Supersedes origin-alignment-2026-10-24-1200.md.

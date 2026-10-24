# Origin alignment check — memkernel-0-5 (the measured run's analysis plan, truncation rule and API-error receipts, FR-015a/FR-016/FR-017/FR-018)

Origin: https://github.com/gosha70/memkernel/issues/17 (direction update posted 2026-10-18, issuecomment-6255377037), and the owner's statements in specs/memkernel-0-5/origin/ (2026-10-15 decisions, 2026-10-16 option B, 2026-10-17 wiki_studio arm, 2026-10-18 wiki-studio 0.4.1, 2026-10-24 measured-run design).

Origin claim:
> Show strong evidence of how memkernel helps with memory and context management, and state clearly what it is and what it is not (it is not a token optimizer). Adopt wiki-studio as the wiki maintainer where the current release is sufficient (lint and health, shared schema) and specify what wiki-studio must expose for the rest (promote gate, schema as code). Finalize the positioning and the wiki-studio contract before the first benchmark run; let the #17 protocol proceed in parallel.

Working claim:
> Before the code freeze, the spec fixes how the measured run is analysed and how its report decides. The task is the unit of inference; the primary endpoint pools all tasks against `claude_md` and `fs_grep` with an exact sign test over non-tied tasks, Holm over the two, and an approximate bootstrap interval for the mean effect; labels are gain, loss, equivalent (interval inside the no-gain band) or no detectable difference, and the headline needs a gain against both. Per-group and secondary results are descriptive. The report computes all of it from the receipts. Receipts gain `api_errors` (schema version 3, version 2 accepted only for calibration); a strict tail of non-authentication API errors, ordered by `started_at` across the run, truncates it: truncated trials are a third category, neither invalid nor scored, and a pair is removed when either trial is truncated, instead of being scored against whichever arm ran last; other API errors stay scored and counted. The measured run gets a $150 spend limit, and preflight refuses to start when the estimate, computed from the committed calibration receipts at the preregistered prices and runs, plus 30 percent exceeds it. Arms, tasks and persistence rules are unchanged.

Mismatches:
  - none. Strong evidence needs a preregistered decision rule the report actually applies, a design that can reach a conclusion at this size without overstating one, and environment failures kept out of the arms' scores.

Verdict: aligned
Confidence: high

Notes:
  - Supersedes origin-alignment-2026-10-23-1200.md.
  - The owner's approval is quoted in specs/memkernel-0-5/origin/2026-10-24-measured-run-design.md.

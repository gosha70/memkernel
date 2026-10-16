# Origin alignment check — memkernel-0-5 (after the option B amendment)

Origin: https://github.com/gosha70/memkernel/issues/17, wiki-studio v0.1.0 and its `docs/consumers.md`, the user's statements in specs/memkernel-0-5/origin/2026-10-15-decisions.md, and the owner's decision of 2026-10-16 in specs/memkernel-0-5/origin/2026-10-16-option-b.md.

Origin claim:
> Show strong evidence of how memkernel helps with memory and context management, and state clearly what it is and what it is not (it is not a token optimizer). Adopt wiki-studio as the wiki maintainer where the current release is sufficient (lint and health, shared schema) and specify what wiki-studio must expose for the rest (promote gate, schema as code). Finalize the positioning and the wiki-studio contract before the first benchmark run; let the #17 protocol proceed in parallel.

Working claim:
> Track A is unchanged (US1 released as 0.4.1; US2 tasks 5–8 merged; tasks 9–10 wait on wiki-studio 0.2). Track B now delivers the evidence for memory and context management as a maintainer-run supplemental evaluation: a stdlib runner bounded to four lifecycle groups (retain across sessions, revalidation after a repository change, sharing through the wiki bridge, recovery across compaction) on tasks in agent-memory-bench's executable task format; six arms with frozen persistence rules and identical first-session information (`bare`, `placebo`, `protocol`, `claude_md`, `fs_grep`, `memkernel`), the files-carry-state arms as the primary comparison; a credential-free demonstration with simulated events; a calibration run that proves live compaction and fixes the budget and is never scored; a preregistration announced on #17 before a freeze-verified measured run; a report labelled maintainer-run, with failures and nulls. Entering agent-memory-bench as a retrieval arm continues upstream and is not a release gate.

Mismatches:
  - none. The amendment moves closer to the origin: the lifecycle claims are the "memory and context management" the origin names, and the earlier plan would have produced no evidence for them in 0.5.0. The one deliberate trade is credibility (an own runner rather than the third-party harness), stated in the report label and recorded in the origin note with the task 11 evidence that required it.

Verdict: aligned
Confidence: high

Notes:
  - Supersedes origin-alignment-2026-10-15-1838.md, whose addendum recorded that task 11 made US3/US4 infeasible as written.
  - Revised after review of PR #22 (2026-10-16): the `lc-wiki` wiki directory is a declared shared artifact for every arm with an empty destination store; `lc-compact` trials need per-trial evidence that compaction fell between exposure and use, with preregistered exclusion and pairing rules (FR-015a); receipts follow a versioned schema with timestamps, chain position, admission status, configuration and preregistration bindings, and diagnostic numerators and denominators. Origin unchanged; these tighten the experiment contract only.
  - Second revision on PR #22: trial validity separates verified harness failures and missing compaction (invalid, excluded) from agent timeouts, hook failures and wrong or missing answers (valid failures in the primary endpoint); exposure and evaluation stages are runner-controlled; a hooks-succeeded analysis is secondary and labelled. Origin unchanged.
  - Amended 2026-10-16 after wiki-studio 0.2.0/0.3.0 shipped and PR #24's review: FR-007 now specifies the scaffold-first gated export verified against 0.3.0 and an explicit proposals directory; SC-2 compares pages, index.md and log.md only; FR-015 and FR-018 require a disposable credential-free machine and a separate low-limit key revoked after the run, stated in the report. Origin unchanged.

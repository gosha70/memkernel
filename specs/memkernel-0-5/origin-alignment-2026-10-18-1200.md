# Origin alignment check — memkernel-0-5 (`wiki_studio` arm re-pinned to wiki-studio 0.4.1)

Origin: https://github.com/gosha70/memkernel/issues/17, https://github.com/gosha70/wiki-studio/issues/10, wiki-studio `v0.4.1` `docs/agent-arm/` (read 2026-10-18), and the owner's statements in specs/memkernel-0-5/origin/2026-10-15-decisions.md, 2026-10-16-option-b.md, 2026-10-17-wiki-studio-arm.md and 2026-10-18-wiki-studio-0-4-1.md.

Origin claim:
> Show strong evidence of how memkernel helps with memory and context management, and state clearly what it is and what it is not (it is not a token optimizer). Adopt wiki-studio as the wiki maintainer where the current release is sufficient (lint and health, shared schema) and specify what wiki-studio must expose for the rest (promote gate, schema as code). Finalize the positioning and the wiki-studio contract before the first benchmark run; let the #17 protocol proceed in parallel.

Working claim:
> Unchanged design from the 2026-10-17 record. The `wiki_studio` arm now pins wiki-studio 0.4.1 (CLI pin, source tag and commit, the calibration image, the development lock), whose promote restores the whole wiki when a write fails part-way (wiki-studio#21). Its instruction and upstream configuration keys are byte-identical to the v0.4.0 ones. The version is fixed from calibration through the measured run; nothing has been calibrated or preregistered.

Mismatches:
  - none. The re-pin happens before the first benchmark run, as the origin asks for the wiki-studio contract, and it removes a way the shared wiki could be corrupted during a measured run without changing what any arm is told or keeps.

Verdict: aligned
Confidence: high

Notes:
  - Supersedes origin-alignment-2026-10-17-1200.md.
  - FR-007's snapshot workaround stays (floor 0.3.1); removing it is deferred to after the measured run.

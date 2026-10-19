# Origin alignment check — memkernel-0-5 (calibration done; wiki-bridge wiring check, task 18a)

Origin: https://github.com/gosha70/memkernel/issues/17 (direction update posted 2026-10-18, issuecomment-6255377037), and the owner's statements in specs/memkernel-0-5/origin/ (2026-10-15 decisions, 2026-10-16 option B, 2026-10-17 wiki_studio arm, 2026-10-18 wiki-studio 0.4.1).

Origin claim:
> Show strong evidence of how memkernel helps with memory and context management, and state clearly what it is and what it is not (it is not a token optimizer). Adopt wiki-studio as the wiki maintainer where the current release is sufficient (lint and health, shared schema) and specify what wiki-studio must expose for the rest (promote gate, schema as code). Finalize the positioning and the wiki-studio contract before the first benchmark run; let the #17 protocol proceed in parallel.

Working claim:
> Calibration ran on 2026-10-18 (claude-sonnet-5-5, image memkernel-calibration:12a3ff3b60e3, in a throwaway Lima VM): 50 valid ungraded sessions, live compaction recorded between exposure and evaluation in 12 of 12 compaction sessions with memkernel's PreCompact/PostCompact hooks succeeding. The memkernel arm never called wiki_export or wiki_import, so calibration does not show the wiki bridge works. Before the freeze, a credential-free, ungraded wiring check on a synthetic fixture (task 18a) drives the real MCP server through export, the runner's wiki-only transfer and import into an empty second namespace, read-only in the calibrated image. No arm, task or instruction changes.

Mismatches:
  - none. The check adds evidence for one of the four lifecycle claims ("sharing through the wiki bridge") without touching the measured design; a defect it finds is fixed, documented and recalibrated before the freeze.

Verdict: aligned
Confidence: high

Notes:
  - Supersedes origin-alignment-2026-10-18-1200.md.

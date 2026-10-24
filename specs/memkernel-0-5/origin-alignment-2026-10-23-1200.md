# Origin alignment check — memkernel-0-5 (a refused API key makes a trial invalid, FR-015a/FR-018)

Origin: https://github.com/gosha70/memkernel/issues/17 (direction update posted 2026-10-18, issuecomment-6255377037), and the owner's statements in specs/memkernel-0-5/origin/ (2026-10-15 decisions, 2026-10-16 option B, 2026-10-17 wiki_studio arm, 2026-10-18 wiki-studio 0.4.1).

Origin claim:
> Show strong evidence of how memkernel helps with memory and context management, and state clearly what it is and what it is not (it is not a token optimizer). Adopt wiki-studio as the wiki maintainer where the current release is sufficient (lint and health, shared schema) and specify what wiki-studio must expose for the rest (promote gate, schema as code). Finalize the positioning and the wiki-studio contract before the first benchmark run; let the #17 protocol proceed in parallel.

Working claim:
> A recalibration attempt on 2026-10-22 ran with a key that stopped working partway: 24 sessions failed with "Invalid API key", and 12 were recorded as valid trials, which in a measured run would count as failures of the arm that happened to be running. FR-015a now makes a refusal of the run's key at any step a third invalid reason, `authentication_failed`, established only from fields the CLI sets in the stream (a result's api_error_status 401 or 403, or an assistant message's error authentication_failed), never from the model's text; it removes its pair and counts per arm and reason like the other invalid reasons. FR-018's closed invalid_reason list gains the value; receipts stay at schema version 2. This decides which trials the measured run excludes, before the preregistration cites it; it changes no arm, task or measurement.

Mismatches:
  - none. Strong evidence needs failures of the environment kept out of the arms' scores and visible as such; the rule stays runner-evidence-only.

Verdict: aligned
Confidence: high

Notes:
  - Supersedes origin-alignment-2026-10-21-1200.md.

# Licensing across the memkernel ecosystem

Reviewed 2026-10-11 from the `LICENSE` files in each checkout; memkernel relicensed the same day.

## Current state

| Repository | License today | Role in the ecosystem |
|---|---|---|
| memkernel | **Apache-2.0** (relicensed from MIT on this branch, 2026-10-11) | library + MCP server, consumed by everything |
| rlm-studio | MIT | library (document layer, ADR-009) |
| code-copilot-team | MIT | harness configuration framework, consumer |
| my-llm | MIT | unrelated lab |
| haa | Apache-2.0 | runtime harness, consumer |
| mapatlas | Apache-2.0 | unrelated |
| document-assistant | CC-BY-SA-4.0 | source of the future `ragkit` extraction |
| ragkit (old) | **no LICENSE file** (README/pyproject silent) | to be retired |
| ai-wiki | Apache-2.0 (created 2026-10-11, empty) | receives the wiki maintainer extracted from code-copilot-team (MIT) |
| ragkit (new) | — | to be extracted from document-assistant (CC-BY-SA-4.0) |

## Recommendation

1. **Libraries other projects embed: Apache-2.0.** memkernel, the new
   `ai-wiki`, the new `ragkit`, and rlm-studio are dependencies of other
   people's harnesses. Apache-2.0 adds an explicit patent grant and
   contributor terms that MIT lacks, is what haa and mapatlas already use,
   and is the common choice for infrastructure (Chroma, sentence-transformers'
   upstream, LiteLLM are all Apache-2.0 or MIT, both compatible). Moving an
   MIT project to Apache-2.0 is a one-way, permissive-to-permissive change
   that requires the consent of every copyright holder; for single-author
   repositories that is one commit.
2. **If staying on MIT is preferred, that is also fine.** MIT and
   Apache-2.0 code can depend on each other in either direction. The only
   thing to avoid is a mixed set *with a share-alike license in the chain*.
   Pick one of the two for all new repositories and do not split.
3. **document-assistant must leave CC-BY-SA-4.0 before anything is
   extracted from it.** Creative Commons itself recommends against CC
   licenses for software (no patent language, unclear on linking, and
   ShareAlike would pull every dependent into CC-BY-SA). The owner can
   relicense because they hold the copyright, provided no external
   contributor has merged code under CC-BY-SA (check `git shortlog -s`).
   Do this *before* creating the new `ragkit` so its history starts clean.
4. **Old ragkit: add a LICENSE before archiving** (MIT or Apache-2.0, same
   as the owner's choice above) so the archived repository is not
   "all rights reserved" by default, then mark it archived on GitHub with a
   README pointer to the new `ragkit`.
5. **Copyright headers.** memkernel and rlm-studio files carry
   `Copyright (c) EGOGE - All Rights Reserved.` followed by the MIT grant.
   "All Rights Reserved" contradicts an open-source grant in spirit (it is
   legally inert under Berne, but it confuses readers and some license
   scanners). Use `Copyright (c) 2026 EGOGE` + the SPDX line
   `SPDX-License-Identifier: MIT` (or `Apache-2.0`) instead, as mapatlas
   already does.
6. **Third-party notices.** Apache-2.0 projects should ship a `NOTICE`
   file listing bundled third-party code; memkernel currently bundles none
   (everything is a pip dependency), so only the hook templates copied
   into other repos need to keep their header.

## Resulting matrix (if recommendation 1 is taken)

| Repository | Target |
|---|---|
| memkernel, ai-wiki, ragkit (new), rlm-studio | Apache-2.0 |
| haa, mapatlas | Apache-2.0 (unchanged) |
| code-copilot-team | MIT (unchanged; a configuration framework, not an embedded library) |
| document-assistant | Apache-2.0 (relicensed from CC-BY-SA-4.0) |
| ragkit (old) | MIT or Apache-2.0 added, then archived |

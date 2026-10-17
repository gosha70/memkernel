# Origin alignment check — memkernel-0-5 (seventh arm `wiki_studio`, catch-up corrections)

Origin: https://github.com/gosha70/memkernel/issues/17 (read 2026-10-17), wiki-studio v0.1.0 `docs/consumers.md`, https://github.com/gosha70/wiki-studio/issues/10 and `docs/agent-arm/` at `v0.4.0` (read 2026-10-17), and the owner's statements in specs/memkernel-0-5/origin/2026-10-15-decisions.md, 2026-10-16-option-b.md and 2026-10-17-wiki-studio-arm.md.

Origin claim:
> Show strong evidence of how memkernel helps with memory and context management, and state clearly what it is and what it is not (it is not a token optimizer). Adopt wiki-studio as the wiki maintainer where the current release is sufficient (lint and health, shared schema) and specify what wiki-studio must expose for the rest (promote gate, schema as code). Finalize the positioning and the wiki-studio contract before the first benchmark run; let the #17 protocol proceed in parallel.

Working claim:
> Track A is complete: wiki_export writes through wiki-studio's promote gate with the extra at >=0.3.1 (CI locked to 0.4.0), fails closed on a broken installation, and restores the wiki itself because promote's rollback misses partial writes (wiki-studio#21). Track B is unchanged in memkernel's design (four lifecycle groups, frozen persistence rules, memkernel against claude_md and fs_grep as the primary endpoint) and gains a seventh arm, `wiki_studio`, on `lc-wiki` only: wiki-studio's model-free CLI through Bash, nothing persisted beyond the shared wiki, compared against the same files-carry-state controls in its own table, with no memkernel-versus-wiki_studio claim. Calibration is ungraded with workspace cleanup and keeps only receipts and raw streams, which it states is not blinding.

Mismatches:
  - none. #17 lists "knowledge shared across agents or people" among the scenarios where memory should win and asks whether a memory server adds value over the files teams already use; `wiki_studio` is a curated-files approach on exactly that scenario (`lc-wiki`), so it sharpens the comparison the origin asks for. The arm is also evidence for wiki-studio (#10), which goes beyond memkernel's own claim; the owner decided to include it (origin/2026-10-17-wiki-studio-arm.md), and memkernel's endpoint, label and minimum pairs are kept separate from it so it cannot change what is claimed for memkernel.

Verdict: aligned
Confidence: high

Notes:
  - Supersedes origin-alignment-2026-10-16-0900.md.
  - Catch-up corrections in the same amendment: FR-005/FR-007/FR-009 floor `>=0.3.1` (the first release with py.typed) and the fail-closed and snapshot behaviour merged in #26; FR-015 "ungraded, with workspace cleanup" as merged in #28; `runner.py demo` (the subcommand) in FR-014, SC-4 and the US3 checkpoint.
  - Nothing has been calibrated or preregistered; task 17a lands before task 18.
  - Budget control corrected on review: the spend cap is a workspace limit (Anthropic documents spend limits per workspace, https://platform.claude.com/docs/en/manage-claude/workspaces), so each paid run uses a dedicated workspace with a verified spend limit and a key scoped to it; FR-015, FR-018 and tasks 18, 20, 21 say so. Origin unchanged.

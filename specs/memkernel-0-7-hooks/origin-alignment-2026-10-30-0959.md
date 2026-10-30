# Origin alignment check — memkernel-0-7-hooks (#59 D5–D9)

Origin: https://github.com/gosha70/memkernel/issues/59, https://github.com/gosha70/memkernel/issues/68, the Claude Code hooks reference, and specs/memkernel-0-7-hooks/origin/2026-10-30-d5-d9.md.

Origin claim:
> #59's D5 (no ref_id on context lines), D6 (no absolute relevance floor; reinforcing touch), D7 (no size limit under the 10,000-character cap), D8 (the same fact twice), D9 (no SessionEnd hook; a spool marker only). The owner's go: "spec for D5–D9 (D9 its own phase), including the README protocol's relevance-ranked 'latest checkpoint' for agents."

Working claim:
> Phase 1: ref_ids on every injected line; a floor on dense similarity with touch=False; per-section budgets under 9,000 characters; in-block de-duplication and instructions that stop repeating the hooks; recall gains order="newest" (a parameter, so still nine tools) used everywhere agents look for the latest checkpoint; the 0.5 arms test compares against a frozen copy so the template can change. Phase 2 (D9): a SessionEnd spool writer with no store or model, drained at the next startup with a one-line notice. Decisions H1–H4 are open for the owner to confirm.

Mismatches:
  - none. D5–D9 are each requirements, D9 is its own phase, and the agents' relevance-ranked latest checkpoint is FR-005. Transcript capture (#59 Phase 2) is excluded, as the origin places it later.

Verdict: aligned
Confidence: high

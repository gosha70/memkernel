# Origin note: a seventh arm, `wiki_studio`, on `lc-wiki` (2026-10-17)

Decision by the repository owner on 2026-10-17. Asked whether to add the
`wiki_studio` arm before the 0.5 code freeze (on `lc-wiki` only) or defer it
past 0.5, the owner answered:

> add

Where the arm comes from. wiki-studio 0.4.0 (tag `v0.4.0`, `e9ec3fa`) ships
`docs/agent-arm/`: a `config.frozen.json` in this suite's format, an
instruction of 1,769 bytes (memkernel's block is 1,832; the placebo rule is
within 5 percent), and the list of changes memkernel needs. The arm uses only
the model-free verbs `wiki-studio info`, `find`, `init` and
`propose --from DIR --promote` through Bash, and never `ingest` or `query`,
which start a second model whose tokens the receipts would not see.
gosha70/wiki-studio#10 (agent-level evidence that consulting the wiki helps)
stays open until this run is published.

Why it is in this release. Nothing had been calibrated or preregistered
when the decision was made: adding the arm changes an approved spec, not a
preregistered design, and costs about five `lc-wiki` trials per run plus its
calibration cells. After the freeze, `check_freeze.py` would refuse it, and
it would need its own calibration and paid run.

Limits that come with the decision:
- The arm runs on `lc-wiki` only. On `lc-retain` and `lc-reval` it persists
  nothing and would behave like `protocol`; on `lc-compact` it measures
  nothing specific to the wiki.
- It is a second treated arm with its own comparison against the same
  primary comparators (`claude_md`, `fs_grep`), reported in its own table.
  memkernel's primary endpoint, label and minimum pairs are unchanged, and no
  head-to-head memkernel-versus-wiki_studio claim is preregistered.
- Breaches of the arm's instruction are visible in receipts as diagnostics,
  not exclusions (FR-015a).

Unchanged: the origin claim in `plan.md`, Track A, memkernel's comparisons,
the preregistration and freeze rules, no LLM judge, no token-savings claim.

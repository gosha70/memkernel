# Origin note: the measured run's analysis plan and spend limit (2026-10-24)

Decision by the repository owner on 2026-10-24, after the clean calibration
(`calibration-20261024T033046Z`, `eval/lifecycle-suite/calibration/RECORD-2026-10-24.md`)
and two rounds of external review of the proposed design. Asked to agree to
the whole design and to approve the measured run's spend limit, the owner
answered:

> 1. agree 2. "$150 approved"

Why the design changed before the freeze. FR-016 required the
preregistration to name a threshold and a no-gain band, but `report.py`
applied no decision rule, and FR-018 requires every number in the report to
come from the receipts through the report step. Review then showed that a
per-group McNemar test at 0.05 would run eight tests (a 34 percent chance of
a false gain), treat correlated runs of one task as independent pairs, and
call a point estimate inside a band "no gain". Pooling all tasks with the task
as the unit is the only design here that can reach a conclusion: a group has
five tasks, and the best two-sided sign test over five is p = 0.0625.

What was agreed (the values the preregistration carries; FR-015a, FR-016,
FR-017 and FR-018 as amended on 2026-10-24 state the method):
- Measured set: all 20 tasks (calibration is discarded wholesale, so it may
  use measured tasks). Arms as frozen; `wiki_studio` on `lc-wiki` only.
- Runs per arm per task: 5, so up to 100 pairs per primary comparison and 25
  per group.
- Unit of inference: the task. Primary endpoint: all tasks pooled, against
  `claude_md` and against `fs_grep`; exact two-sided sign test over non-tied
  tasks, ties reported; Holm over the two at α = 0.05; mean effect in
  percentage points, tasks weighted equally, with an approximate 95 percent
  percentile bootstrap interval (resample count and seed fixed in the
  preregistration).
- Labels: gain, loss, equivalent (the whole interval inside a no-gain band of
  ±10 points), no detectable difference. Headline gain only when both primary
  comparators show a gain, deliberately stricter than needed.
- Per-group, secondary (`bare`, `placebo`, `protocol`) and `wiki_studio`
  results: descriptive only.
- Inferential label: at least 80 valid pairs covering at least 16 tasks per
  primary comparison. `lc-compact` measured with at least 10 valid pairs;
  the `wiki_studio` comparison with at least 10.
- API errors: every receipt counts them by status (`api_errors`, schema
  version 3). A strict tail of non-authentication API errors truncates the
  run: those sessions are listed, not scored. Other API errors stay scored
  and are counted by arm.
- Spend: the measured run gets its own dedicated workspace with a **$150**
  monthly spend limit, verified before the first session. Estimated cost
  about $81 (calibration's per-chain usage at Claude Sonnet 5.5's prices of
  2026-10-15, with compaction input at the full input price and a 20 percent
  allowance for invalid trials); the preregistration recomputes it at the
  prices current when it is written. `preflight` refuses to start when the
  estimate plus 30 percent exceeds the limit.

Unchanged: the origin claim in `plan.md`, the arms, tasks and persistence
rules, the primary comparators, FR-015a's three invalid reasons, no LLM
judge, no token-savings claim, the freeze and announcement rules.

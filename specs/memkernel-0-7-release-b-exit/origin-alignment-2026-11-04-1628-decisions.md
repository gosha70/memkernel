# Origin alignment check — memkernel-0-7-release-b-exit, after the owner's decisions

Origin: as before, plus the owner's message of 2026-11-04: "I confirm E1–E6 as recommended. E7: yes, as a
separate upgrade run with its own directory, not before session 1. R2: kill between the replacement's write and
the predecessor's supersession mark (wiki-scope's interrupted supersession). E5: add a path filter
(src/memkernel/, eval/release-b-exit/, the workflow)."

Origin claim:
> E1–E6 as recommended; E7 a separate upgrade run with its own directory; R2 at the interrupted supersession; E5
> with the path filter.

Working claim:
> plan.md records the decisions; R2 kills the import between `_write_record` of the replacement and
> `_mark_superseded` of its predecessor (one ref_id, wrapped in the run's own process) and the next import
> completes it; E7 is `run.py --upgrade` in its own run directory (0.6.0 store, upgrade, `ambiguous`,
> `adopt_legacy`, one 0.7 correction); E5 runs on PRs touching src/memkernel/**, eval/release-b-exit/** or the
> workflow, weekly and by dispatch. spec.md gains FR-005; tasks.md gains the upgrade tasks.

Mismatches:
  - none.

Verdict: aligned
Confidence: high

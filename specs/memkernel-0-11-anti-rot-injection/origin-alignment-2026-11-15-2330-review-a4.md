# Origin alignment check — memkernel-0-11-anti-rot-injection, second review of #131 (A4 proposed)

Origin: gosha70/memkernel#128 (origin/2026-11-15-issue-128.md).

Origin claim: as in plan.md.

Working claim:
> As amended (A1–A3), with A4 proposed: the calibrated default needs refs/main to equal the full calibrated SHA; the complete
> #57 judgement on both hook paths' final five displayed memories, with three recorded failure kinds, any of which fails it.

Mismatches:
  - none. A4 keeps the default floor off unless its calibration is valid for the model actually loaded.

Verdict: aligned
Confidence: high

Note: after DeepSeek round 3, SC-3 names required targets; the D3 warning is logged once at service build; an explicit floor on an uncalibrated embedder logs one info line.

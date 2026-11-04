# Origin alignment check — memkernel-0-7-release-b-exit, at the spec PR

Origin: as in the first record, plus the owner's message of 2026-11-04: "go: push the exit-run plan as a
spec-only PR with E1–E6 still as recommendations, and note in it where upgrade-path adoption (0.6 → 0.7) is
tested. I'll decide E1–E6 after the reviewer has read it."

Origin claim:
> The plan as drafted, E1–E6 as recommendations, plus a note on where 0.6 → 0.7 adoption is tested.

Working claim:
> The plan gains "The upgrade path (0.6 → 0.7): where adoption is tested": only simulated 0.6 stores, in five
> test files; no test opens a store memkernel 0.6.0 wrote. It adds an optional E7 (a 0.6.0 session 0 and an
> upgrade before session 2), a recommendation like E1–E6.

Mismatches:
  - E7 goes past the owner's ask (a note); it is a recommendation only, for the owner to take or drop.

Verdict: aligned
Confidence: medium

# Origin alignment check — memkernel-0-7-release-b-exit, R4's release order

Origin: as before, plus the owner's message of 2026-11-04: "In R4, release the first import only after the
second has written a marker that it reached its import, then the hold".

Working claim:
> R4: the second process writes a reached-the-import marker right before its import call; the run releases the
> first only after that marker plus a fixed hold; the second's first write must come after the release.

Mismatches:
  - none.

Verdict: aligned
Confidence: high

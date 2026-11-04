# Origin alignment check — memkernel-0-7-governed, the build after the reviewer's second build review

Origin: as in origin-alignment-2026-11-04-0910-build-review1.md, plus the reviewer's second build review (pasted
by the owner) and the owner's own answer of 2026-11-04 on G2: "Synchronous start (Recommended)": start the child
on the calling thread and take the 2.5-second bound from once `Process.start()` returns.

Origin claim:
> As before; G2's bound covers the check once the child has started, not a fork or exec the operating system
> holds up.

Working claim:
> The helper start thread is gone: `Process.start()` runs on the calling thread and the deadline is taken once it
> returns. The pipe allocation and every cleanup step are inside the no-raise boundary, each cleanup step running
> whatever the one before it did.

Mismatches:
  - none against the origin. G2's amendment is the owner's decision. G3's null `remaining`, G5's rename
    supersession and SC-1's helper changes were confirmed in the reviewer's pasted review; spec.md still marks
    them as awaiting the owner's own confirmation.

Verdict: aligned
Confidence: medium

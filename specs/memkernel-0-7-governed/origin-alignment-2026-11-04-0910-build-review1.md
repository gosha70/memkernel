# Origin alignment check — memkernel-0-7-governed, the build after the reviewer's first build review

Origin: as in origin-alignment-2026-11-04-0826-build.md, plus the reviewer's build review of 2026-11-04 (pasted
by the owner; the reviewer's findings, not the owner's decisions).

Origin claim:
> As before. G1: the governed preflight before any page write or read. G2: the session-start hook never fails
> because of the debt, and the debt's total time is bounded.

Working claim:
> The governed export runs its preflight before it reads the wiki and lints nothing after a refusal (`remaining`
> null). The debt's pipe, start and cleanup are inside one no-raise boundary; `Process.start()` runs in a helper
> thread, so a stalled start is the unavailable line at the deadline and the thread cleans up later. The
> in-memory snapshot checks the deadline before and after its blocks. `sha:` is asked of git at the source's own
> (lexical) path. A negative export batch is refused.

Mismatches:
  - none against the origin. spec.md records three build amendments (G2's start thread, G3's null `remaining` on a
    preflight refusal, G5's rename supersession with SC-1's three helper changes), accepted in the reviewer's
    review where it says so, all awaiting the owner's confirmation.

Verdict: aligned
Confidence: medium

# Origin alignment check — memkernel-0-7-governed, after the third review

Origin: as in the previous record, plus specs/memkernel-0-7-governed/origin/2026-11-03-review-3.md.

Origin claim:
> As before; the third review: all parent-side blocking work inside the bounded child, every wait bounded, a locked (shared, non-blocking) disk snapshot, and a specified Pipe-based result with cleanup on every path.

Working claim:
> The parent checks settings and takes only the non-blocking in-memory snapshot; detection, the preflight, findings and the disk snapshot (non-blocking shared flock on the existing lock file) run in one spawned child. One monotonic deadline set before start; a one-way Pipe with a bounded plain dict, poll(remaining), recv before join; terminate, bounded join, kill, bounded join, total at most 2.5 s; an unreaped child is reported, not closed; both pipe ends closed in finally and Process.close() after reaping.

Mismatches:
  - none against the origin; the decisions await the owner.

Verdict: aligned
Confidence: medium

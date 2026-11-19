# Origin alignment check — fix-148-http-host-origin

Origin: gosha70/memkernel#148 (origin/2026-11-18-issue-148.md), with the correction found while building.

Origin claim: as in plan.md.

Working claim:
> Host/Origin checks following MEMKERNEL_HOST on every bind (loopback as the SDK already does, a specific address,
> a wildcard bind with MEMKERNEL_ALLOWED_HOSTS or unchecked with a warning); README and a CHANGELOG Security entry.

Mismatches:
  - partial, factual: the issue says the HTTP transport has no check; the SDK already protects loopback binds, so
    the gap is non-loopback binds only. The fix delivers what the issue proposes; the issue, #141 and the PR are
    corrected to the narrower scope.

Verdict: aligned
Confidence: high

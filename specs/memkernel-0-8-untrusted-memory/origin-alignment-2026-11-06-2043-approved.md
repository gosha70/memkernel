# Origin alignment check — memkernel-0-8-untrusted-memory, approved

Origin: as before, plus the owner's message of 2026-11-06: "In #105's U2, also neutralise the tag with whitespace
after < or / (< stored-memory, </ stored-memory>), and add those to SC-2. The plan is approved."

Working claim:
> U2 neutralises `<\s*/?\s*stored-memory`, case-insensitive; SC-2 lists the whitespace forms; plan.md is approved.

Mismatches:
  - none.

Verdict: aligned
Confidence: high

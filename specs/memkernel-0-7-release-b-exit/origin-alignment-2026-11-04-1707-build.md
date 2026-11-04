# Origin alignment check — memkernel-0-7-release-b-exit, the US1 build

Origin: the merged spec (#97, 45e0385) with the owner's decisions, plus the owner's message of 2026-11-04: "In R4,
release the first import only after the second has written a marker that it reached its import, then the hold
... go: merge #97 (merge commit), then build the exit run as its own PR for review."

Working claim:
> eval/release-b-exit/run.py (the main run, sessions 1–4 with two curator rounds, R1–R4, and the upgrade run),
> record.py (wiki-studio's protocol on released wheels), README, and .github/workflows/release-b-exit.yml (paths
> filter, weekly, dispatch; informational). R4's marker is written when the second import asks for the store's
> lock, after its preflight: still "reached its import", without the pre-lock work inside the hold.

Mismatches:
  - The plan's sessions 1–3 became sessions 1–4 with two curator rounds: memkernel withdraws a deprecated or
    deleted page's memory only once that page was imported, so the pages are imported (session 2) before the
    curator deprecates, deletes, supersedes and edits them (curator 2, session 3).
  - R4's marker moved from before the import call to the lock request (above); plan.md says so.

Verdict: aligned
Confidence: high

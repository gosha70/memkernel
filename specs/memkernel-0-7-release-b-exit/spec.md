# Spec: the Release B exit run (#48)

Origin and facts are in `plan.md` and `origin/2026-11-04-exit-run.md`. Draft, for review; the decisions E1–E7
await the owner.

## Requirements
- **FR-001:** `eval/release-b-exit/run.py` runs sessions 1–3 and the curator step as separate processes on one
  persisted store and one governed wiki, in `MEMKERNEL_WIKI_MODE=governed`, and prints every check by name.
- **FR-002:** retries R1–R4 are injected from the run script's own process, and each converges, as the plan's
  convergence summary defines it. That means the same live pages, live memories (by page key and content) and
  withdrawn or superseded records as a fault-free run; no page key with two live memories; no duplicate page or
  receipt; and no unfinished ledger entry.
- **FR-003:** `eval/release-b-exit/record.py` follows wiki-studio's recording protocol: clean tree, full SHA,
  extracted commit, PyPI wheels checked by sha256, pinned embedding revision, run once, failed attempts kept.
  The manifest records the versions, the hashes, every check and the convergence summary. Runs are compared by
  that summary, never by a byte hash.
- **FR-004:** an informational workflow runs `run.py` on pull requests and weekly against a wheel built from the
  PR (E5); not a required check.

## Constraints
- Released wheels only for the recorded run (E1); no model backend; no MCP server; base wiki-studio only (#95).
- No change to memkernel's runtime code: a defect the run finds is its own issue and fix.
- Never touch `.github/workflows/ci.yml`; a new workflow file for E5.

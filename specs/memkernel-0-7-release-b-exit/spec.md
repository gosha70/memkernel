# Spec: the Release B exit run (#48)

Origin and facts are in `plan.md` and `origin/2026-11-04-exit-run.md`. Draft, for review. The owner
confirmed E1–E6 and decided E7, R2 and E5's path filter on 2026-11-04.

## Requirements
- **FR-001:** `eval/release-b-exit/run.py` runs sessions 1–3 and the curator step as separate processes on one
  persisted store and one governed wiki, in `MEMKERNEL_WIKI_MODE=governed`, and prints every check by name.
- **FR-002:** retries R1–R4 are injected inside the session processes that `run.py` starts, and each converges
  as `plan.md`'s Retries section defines it. That section is the normative definition.
- **FR-003:** `eval/release-b-exit/record.py` follows wiki-studio's recording protocol: clean tree, full SHA,
  extracted commit, PyPI wheels checked by sha256, pinned embedding revision, run once, failed attempts kept.
  The manifest records the versions, the hashes, every check and the convergence summary. Runs are compared by
  that summary, never by a byte hash.
- **FR-004:** an informational workflow runs `run.py` against a wheel built from the PR (E5). It runs on pull
  requests that change `src/memkernel/**`, `eval/release-b-exit/**` or the workflow file, weekly, and by
  dispatch. It is not a required check.
- **FR-005 (E7):** `run.py --upgrade` runs the upgrade run in its own directory. It starts with a store written
  by memkernel 0.6.0 from PyPI, upgrades to 0.7.x, and checks:
  - the first import reports every page `ambiguous` and writes nothing;
  - `adopt_legacy=true` adopts each page's record once;
  - one correction loop then completes on the adopted store.
- **R2 (FR-002):** the import is killed between the replacement's write and the predecessor's supersession mark,
  and the next import completes the supersession.

## Constraints
- Released wheels only for the recorded run (E1); no model backend; no MCP server; base wiki-studio only (#95).
- No change to memkernel's runtime code: a defect the run finds is its own issue and fix.
- Never touch `.github/workflows/ci.yml`; a new workflow file for E5.

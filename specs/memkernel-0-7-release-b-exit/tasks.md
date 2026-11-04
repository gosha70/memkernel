# Tasks: the Release B exit run (#48)

<!-- Build on the owner's go after the plan is approved. -->

## US1: The run script, the recorder and the informational workflow

| # | [P] | Task | File(s) | Owner | Done |
|---|-----|------|---------|-------|------|
| 1 | | Sessions 1–3 and the curator step, the named checks (FR-001) | `eval/release-b-exit/run.py` | build | [ ] |
| 2 | | Retries R1–R4 (FR-002): the in-session wrappers for R2 (`_mark_superseded`, one ref_id) and R4 (`retain`, the marker and timestamps), the expected end state and the convergence checks | `eval/release-b-exit/run.py` | build | [ ] |
| 2a | | The upgrade run, `--upgrade` (FR-005, E7) | `eval/release-b-exit/run.py` | build | [ ] |
| 3 | | The recorder and its protocol README (FR-003) | `eval/release-b-exit/record.py`, `README.md` | build | [ ] |
| 4 | | The informational workflow with its path filter (FR-004) | `.github/workflows/release-b-exit.yml` | build | [ ] |

## US2: The recorded run (owner step, after the 0.7.0 release)

| # | [P] | Task | File(s) | Owner | Done |
|---|-----|------|---------|-------|------|
| 1 | | Record once from a clean tree; commit the run directory alone | `eval/release-b-exit/runs/<date>-memkernel-0.7.0-wiki-studio-<v>/` | owner | [ ] |
| 1a | | Record the upgrade run once, in its own directory (E7) | `eval/release-b-exit/runs/<date>-upgrade-memkernel-0.6.0-to-<0.7.x>-wiki-studio-<v>/` | owner | [ ] |
| 2 | | The #48 comment (E6), after tasks 1 and 1a merge and on the owner's go | — | build | [ ] |

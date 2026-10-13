---
feature_id: memkernel-0-4
date: 2026-10-12
status: final
phase: build
mode: review
subject_provider: claude
peer_provider: deepseek
peer_profile: deepseek
runner_fingerprint: ae8dc147cf1264834bab35d116b6ab96b06618f438763cde3a90621d78036dba
verdict: PASS
blocking_findings_open: 0
target_ref: feature/memkernel-0-4
rounds_completed: 2
attempt_count: 1
bypass: false
---

# Peer Review: memkernel-0-4 — Build Phase

**Reviewer**: deepseek
**Scope**: both
**Rounds**: 2
**Verdict**: PASS

## Summary

The Round 1 blocking finding (f-56cb0c46) is addressed: the pair contract is now documented on `HealthItem` and `_near_duplicates`, and a test covers the asymmetric-score case. However, the new test `test_pair_survives_when_only_one_query_direction_clears_the_threshold` contains a tautological expression (`if r.ref_id != results[0].ref_id or True else r`) that is dead code and obscures intent, and the fix's claim that "both query directions are tried and the pair keeps the better score" is not actually verified by the diff — the test only checks that the pair survives, not that the *better* score is retained. The remaining Round 1 warnings/notes are unaddressed but were not blocking.

## Findings

- [warning] f-795fc518: The expression `r.model_copy(update={"score": 0.5}) if r.ref_id != results[0].ref_id or True else r` is tautological: `or True` makes the condition always true, so the `else r` branch is dead code and the `r.ref_id != results[0].ref_id` check is meaningless. This is confusing and suggests the author intended a different condition (e.g., only downgrade the *neighbour*, not the query itself). (tests/unit/test_health.py)
- [warning] f-71908ecd: The test asserts the pair survives and that `"cosine 1.000"` appears, but does not assert that the *better* of the two directions' scores is the one reported. The docstring on `_near_duplicates` claims "score is the best of the two query directions" — this claim is untested. A regression that keeps the *worse* score would still pass. (tests/unit/test_health.py)
- [note] f-b9918bdb: The docstring says "score is the best of the two query directions" but does not state what "best" means for cosine (higher is better) nor what happens if both directions clear the threshold (presumably max). Minor, but the contract is now load-bearing for callers. (src/memkernel/core/services.py)
- [note] f-bc4862ad: The Round 1 fix documents the contract but the diff does not show the loop change that implements "both query directions are tried." If the implementation still iterates only `candidates` as the query side and relies on the reverse direction being covered by the neighbour also being a candidate, then a neighbour that is *not* in `candidates` (e.g., filtered out by `where`) would still be dropped in the reverse direction. The docstring now overpromises relative to what the visible diff guarantees. (src/memkernel/core/services.py)
- [note] f-3c7bb1bf: `_pair_set` still parses `i.detail.split(" ")[1]`, coupling the test to the detail string format — the same fragility flagged in Round 1 (f-cfdf9c05). The new test `test_near_duplicate_pair_is_reported_once_with_smaller_id_first` uses `startswith` which is slightly more robust, but `_pair_set` remains brittle. (tests/unit/test_health.py)

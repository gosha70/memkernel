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
rounds_completed: 1
attempt_count: 1
bypass: false
---

# Peer Review: memkernel-0-4 — Build Phase

**Reviewer**: deepseek
**Scope**: both
**Rounds**: 1
**Verdict**: PASS

## Summary

This is a release-hygiene changeset (US4) for memkernel 0.4.0: version bumps, CHANGELOG, README/docs updates, roadmap relabeling, and hook/Kiro template additions of `MEMKERNEL_PROJECT_ROOT`. The changes are almost entirely documentation and configuration; the only behavioral code is the `os.environ.setdefault("MEMKERNEL_PROJECT_ROOT", os.getcwd())` lines in three hook templates. I found no blocking correctness or security defects in this diff, but several documentation/consistency issues worth noting.

## Findings

- [note] f-29a628e0: The numbered workflow list inserts item "7. Code snapshots" before the existing "6. Curate" item, producing out-of-order numbering (…5, 7, 6). (README.md)
- [note] f-7cfc57c4: The `memory://status` URI-template fix is described as "registered as a URI template since 0.1", but this diff does not touch the resource registration code — the fix must have landed in an earlier commit of this feature. Confirm the fix is actually present in the branch, otherwise the CHANGELOG claims an unshipped fix. (CHANGELOG.md)
- [note] f-3362f12e: The roadmap marks "Git-diff-driven invalidation of code memories" as `[x]` shipped "as whole-file hash revalidation (no git dependency)". This is a semantic substitution — the roadmap item explicitly said git-diff-driven, and whole-file hashing is a different (coarser) mechanism. Marking it `[x]` overstates completion. (docs/roadmap.md)
- [note] f-9d5d3390: The comment claims "Claude Code runs hooks from the project directory", but the same pattern is applied to `pre-compact.py` and `post-compact.py` without verifying that assumption holds for all three hook invocation contexts. If a hook is ever invoked from a different cwd, `MEMKERNEL_PROJECT_ROOT` silently points at the wrong tree and revalidation reads the wrong files. (templates/hooks/session-start.py)
- [note] f-7fa38bac: The template ships a literal placeholder path. If a user copies the file without editing, revalidation will resolve sources under a nonexistent root and silently flag every code memory as `missing`. (templates/kiro/settings/mcp.json)
- [note] f-458de6d5: The `ask(ref_id, question, mode)` row was added to the tool table, but the diff does not show the corresponding `forget_expired()` row being removed from the same table — verify the table is internally consistent (the diff shows `forget_expired()` replaced by `ask`, which may drop a still-valid tool). (docs/architecture/memory-tiers.md)
- [note] f-cfae826f: The CHANGELOG entry for `VectorStorePort.find_by_hash(..., source=None)` states it "never returns a chunk record", but this diff does not include the port implementation. The claim is unverifiable from this changeset. (CHANGELOG.md)

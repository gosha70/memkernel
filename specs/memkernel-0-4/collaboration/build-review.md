---
feature_id: memkernel-0-4
date: 2026-10-13
status: final
phase: build
mode: review
subject_provider: claude
peer_provider: deepseek
peer_profile: deepseek
runner_fingerprint: ae8dc147cf1264834bab35d116b6ab96b06618f438763cde3a90621d78036dba
verdict: PASS
blocking_findings_open: 0
target_ref: docs/install-notes
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

The change adds `--version`/`--help` handling to the `memkernel` CLI entry point, returning proper exit codes and erroring on unknown arguments, plus README/CHANGELOG install guidance and unit tests. The implementation is small and mostly correct, but there are a few correctness and design concerns around argument handling, the `main()` return-type change, and the `__main__` guard.

## Findings

- [warning] f-52cb771f: `args in (["--version"], ["-V"])` and similar tuple-membership checks only match exact single-flag invocations; combined flags like `--version --help` or `-Vh` fall through to the "unknown arguments" branch, and `--help` combined with anything else is treated as an error rather than help. This is arguably fine, but the tuple-of-lists idiom is fragile and easy to misread as "any of these flags present." (src/memkernel/mcp/server.py)
- [warning] f-20667a3c: `main()` now returns `int` instead of `None`. Any external caller (tests, scripts, packaging entry points) that previously relied on `main()` returning `None` or being callable without capturing a return value is unaffected, but the console-script entry point declared in `pyproject.toml` (e.g. `memkernel = "memkernel.mcp.server:main"`) will now have its return value used as the process exit code by setuptools/pipx wrappers — which is the desired behavior, but only if the entry point is wired to `sys.exit(main())` semantics. Verify the packaging entry point actually propagates the return code; otherwise `--version` may still exit 0 but unknown args may not exit 2 when invoked via the installed console script. (src/memkernel/mcp/server.py)
- [note] f-6dbec803: `sys.exit(main())` is correct here, but the module-level `main()` is also the console-script target. The dual path (module `__main__` vs. installed script) means the return-code contract must hold in both. The test only exercises `main([...])` directly, not the installed-script path. (src/memkernel/mcp/server.py)
- [note] f-2fa776c1: The error message joins args with a space: `' '.join(args)`. If an argument contains a space or shell metacharacter, the message is ambiguous but not dangerous (it goes to stderr, not a shell). Minor. (src/memkernel/mcp/server.py)
- [note] f-abcce646: The test monkeypatches `create_server` but not `MemKernelSettings`; it relies on `MEMKERNEL_TRANSPORT` being read by the real settings class. If settings validation requires other env vars or a project root, this test could become environment-dependent. It currently passes, but it is coupled to settings behavior. (tests/unit/test_cli.py)
- [note] f-655d5197: The README states "There is no npm package: an `npx` install someone suggests is a hallucination." This is accurate but the phrasing ("hallucination") is unusual for user-facing docs and may confuse readers unfamiliar with the LLM-hallucination context. (README.md)
- [note] f-21152f8e: The troubleshooting entry for `memkernel --help` hanging references "versions before 0.4.0" — good, but the CHANGELOG entry for this feature is under an unreleased/0.4 section. Confirm the version number in the README matches the actual release version this ships in. (README.md)

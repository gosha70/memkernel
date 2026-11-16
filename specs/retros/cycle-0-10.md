# Retrospective: the 0.10 cycle (2026-11-09 to 2026-11-15)

From the 0.9.0 release (#116) to the merge of #127. Three features, all spec first: a spec PR, then a build PR.

| Issue | What shipped | PRs | Review rounds on the build |
|---|---|---|---|
| #57 | Research note, decision records in the template, a replay of 12 real decisions | #117, #118, #121 | 2 (#121: pinning, then reproducibility) |
| #120 | Recall log (opt-in) and the repeated-mistake count | #122, #124 | 4 (6, 5 and 3 findings, plus one from DeepSeek) |
| #123 | Decisions that cite files are revalidated and returned flagged | #126, #127 | 3 (the newest path, marked context lines, durable flags) |

Also: the opentelemetry CVE fixed by Dependabot (#125); #85's live check recorded; #57, #120 and #123 closed.

## What went well
- **Evidence changed a design before code.** The #57 replay showed that hiding flagged decisions would have hidden two valid safety rules, so #123 became "flag, don't hide".
- **Spec PRs settled decisions early.** Each feature's owner decisions (D1–D6, D1–D4) were made on the spec, and the builds followed them.
- **Reviews found real defects,** each with a reproducing test: oversized and truncated log records, ambiguous pairing, historical `needs_review`, the shared checkpoint path, hook settings, and durable flags.

## What went wrong
- **Checked facts were wrong twice.** The #120 draft said the spool could map sessions (it is drained) and that session start calls `recall` (it does not). Both were caught in the build, as amendments.
- **#124 needed four review rounds.** The spec did not bound what a log record may hold, or say what a truncated or ambiguous record proves; each round found the next edge.
- **Claims outran the checks.** "mypy strict clean" covered `src/` only, while the eval scripts failed; "12 tests" was 11.
- **#126 merged before its review revisions were pushed,** because they waited for a go. The build PR had to carry them as an amendment.
- **Round trips on pasted approvals.** Several reviewer notes carried a "go"; each needed the owner's own words. The rule held, at the cost of time.

## Actions
1. **Before writing a checked fact about a call path, grep every caller** and cite them. Both wrong facts were call-path claims.
2. **A spec that persists records states their bounds** (size, count, field types) and **what each can prove.** That would have saved #124 two rounds.
3. **Report only what was run.** Name the scope of each check: `mypy src/` and `mypy --strict eval/...` separately; test counts from `--collect-only`.
4. **When a spec PR gets review findings, say at once that it is not ready to merge,** so it is not merged ahead of the fix.
5. **CI type-checks the maintained eval tools.** CI checked `src/` only, and `eval/` by hand. The owner decided
   (2026-11-15) to add `mypy --strict` for the maintained eval tools, listed explicitly
   (`eval/repeat-mistakes/count.py`, `transcripts.py`), not the whole `eval/` tree: PR #129.

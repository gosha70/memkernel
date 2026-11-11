---
feature_id: memkernel-0-10-recall-log
spec_mode: full
status: approved
date: 2026-11-11
collaboration_mode: single
origin:
  issue: gosha70/memkernel#120
  urls:
    - https://github.com/gosha70/memkernel/issues/120
    - https://github.com/gosha70/memkernel/issues/112
  transcripts:
    - specs/memkernel-0-10-recall-log/origin/2026-11-11-issue-120.md
  origin_claim: |
    "Make repeated mistakes countable: a recall log and a counting script." With the log enabled, every recall
    leaves one record, and with it disabled nothing is written; the script, run on a fixture with known repeats
    (one returned before the failure, one retrieval miss, one memory in an unreadable store), reports each in the
    right class; a README section explains how to run the count on your own build and what it can't detect.
---

# Plan: a recall log and a repeated-mistake count (#120)

The spec's checked facts change one part of #120: the session spool is drained at each startup, so session windows
come from the Claude Code transcripts, which the count reads anyway for command output.

## Approach

1. **Setting** (`src/memkernel/config.py`): `recall_log: bool = False`.
2. **Module** (`src/memkernel/recall_log.py`): `append(settings, origin, session_id, query, filters, ref_ids)`,
   locked like the spool, rotating at the D3 bound; nothing for an in-memory store or when disabled; a write error
   is logged once, never raised.
3. **Call sites** (D1): the MCP `recall` tool (`origin="tool"`) and the two lifecycle recalls (`origin="hook"`,
   with the session id).
4. **Counting script** (`eval/repeat-mistakes/`): `count.py` (rule D5, classes D6, linking D2), a temporary
   `transcripts.py` reader for Claude Code, and a fixture builder for the tests.
5. **Tests:** unit tests for the log (on, off, in-memory, rotation, a failing write, both origins); a fixture
   test for the script covering every class and the "a note that mentions it does not count" rule.
6. **Docs:** README configuration row and a "Counting repeated mistakes" section; CHANGELOG.

## Risks

- Transcript format is Claude Code's, undocumented and versioned. The reader is small, tested on a fixture, and
  marked temporary (#59 Phase 2).
- Exact-text matching misses reworded errors; the report says so.

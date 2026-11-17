---
feature_id: memkernel-0-12-capture-core
spec_mode: full
status: draft
date: 2026-11-16
collaboration_mode: single
origin:
  issue: gosha70/memkernel#134
  urls:
    - https://github.com/gosha70/memkernel/issues/134
    - https://github.com/gosha70/memkernel/issues/59
  transcripts:
    - specs/memkernel-0-12-capture-core/origin/2026-11-16-issue-134.md
  origin_claim: |
    "Capture core: read ended sessions' transcripts and store failed-then-fixed commands (#59 Phase 2, S2)." The
    spool exposes every ended session with its transcript_path; a session leaves the spool only after its records
    are durably stored; records are idempotent on (session, record UUID, extractor), with the extractor version as a
    tag; the transcript reader sits behind a TranscriptReaderPort with a Claude Code adapter that the #120 count also
    uses. The owner's decisions: capture off by default; it runs in the startup hook with a time budget and a per-run
    record cap; best-effort redaction of the listed secret shapes; captured records stay out of the promotion
    candidates.
---

# Plan: capture core (#134)

## Approach

1. **Port and adapter:** `TranscriptReaderPort` in `core/ports.py`; the Claude Code adapter graduates
   `eval/repeat-mistakes/transcripts.py` into `src/memkernel/transcripts/claude_code.py`; the #120 count uses it.
2. **Spool:** `drain()` reports every ended window with its `transcript_path`; with capture on, ended sessions stay
   in the spool until `commit()` removes them after their records are stored.
3. **Capture** (`src/memkernel/capture.py`): read, extract failed-then-fixed commands, redact the extracted fields,
   compose the record, store it with the key tags, then commit; within the time budget and the per-run cap; missing transcripts retried, then dropped.
4. **Startup:** `on_session_start` runs capture after the drain and reports one line; `consolidate()` leaves captured
   records out of the promotion candidates.
5. **#120 count:** reads through the adapter and reports captured errors apart from agent-stored ones.
6. **Tests, README, CHANGELOG.**

## Risks

- Claude Code's transcript format is undocumented; the adapter skips what it cannot read, and a format change
  yields no records rather than wrong ones.
- Redaction is best-effort: a secret in a shape the patterns miss is stored. Capture is off by default for this
  reason, and the README says so.
- Capture adds time to normal startup; the time budget and the per-run cap bound it.

# Origin alignment check — memkernel-0-12-capture-core, the draft spec

Origin: gosha70/memkernel#134, its key-change comment, and the owner's decisions of 2026-11-16
(origin/2026-11-16-issue-134.md).

Origin claim: as in plan.md.

Working claim:
> FR-001–FR-012: the spool exposes every ended window with its transcript_path and, with capture on, keeps ended
> sessions until commit() after their records are stored; records keyed by (session, record UUID, extractor) with
> the version as a tag; a TranscriptReaderPort with a Claude Code adapter that the #120 count uses; one extractor,
> failed-then-fixed commands, from structured fields; best-effort redaction of the owner's listed shapes; capture off
> by default, in the startup hook within a time budget and a per-run cap; missing transcripts dropped after bounded
> retries and counted; captured records out of the promotion candidates and quoted per #85; the count reports
> captured errors apart.

Mismatches:
  - one, resolved: the issue's version-supersede rule (requirement 3) is replaced by D1, as the owner decided and
    the #134 comment records.
    The values in D6 (budget, caps, retry limit) are the spec's, as D3 asks, and await the owner's approval.

Verdict: aligned
Confidence: high

## Re-check after DeepSeek round 1 (2026-11-16)

The round-1 fixes clarify FR-001 (reported sessions, miss count), FR-003 (one lookup per session), FR-004 (the
port reads one file), FR-005 (one record per passing run; backticks removed), FR-006 (hex kept; redaction before
composing), FR-007 (soft budget; the hook timeout) and FR-010 (TTL). None changes what the origin asks for.

Verdict: aligned
Confidence: high

## Re-check after DeepSeek rounds 2 and 3 (2026-11-16)

Wording only: the stored fields are one line each without backticks (FR-005), the key lookup ignores the version
(FR-003), the hook timeout's headroom (FR-007), and SC-2 asserts that a committed session is not captured again
after an upgrade. None changes what the origin asks for.

Verdict: aligned
Confidence: high

## Re-check after the owner's additions (2026-11-16)

Origin lines checked: the owner's message after the draft (origin file, last section) and requirement 2 of #134.
- D6 approved; FR-008: an oversized transcript is unreadable and leaves the spool at once, unread; the read of a
  transcript under the cap counts against the budget.
- FR-007: with capture off, the spool behaves as today.
- Checked facts: `is_error` confirmed on real transcripts (non-zero exit true; error printed with exit 0 false);
  fixtures cut from real transcripts.
- New: D7, the command-matching rule, is open. The yield measured while confirming `is_error` (2 exact pairs in 289
  failures) makes the issue's "same command" rule a question for the owner; the spec marks it
  `[NEEDS CLARIFICATION]`, so the spec cannot be approved until it is decided. This does not change what the origin
  asks for.

Verdict: aligned
Confidence: high

Round-5 fixes (pass definition, stat wording, fixture cut) are wording only. Verdict: aligned. Confidence: high.
Round-6 fixes (SC-1 layout, the race case) are wording only. Verdict: aligned. Confidence: high.

## Re-check after D7 (2026-11-16)

Origin line checked: the owner's D7 decision (origin file, last section). D7 is recorded as decided, with the rerun
and pass rules in the owner's terms; "same program and target" is a constraint; the yield under D7 (2 pairs, 1 with
the command's own exit status) replaces the earlier count of 12, which came from a looser rule. No open question
remains.

Verdict: aligned
Confidence: high
The D7 label (owner words vs. this spec's reading) is wording only. Verdict: aligned. Confidence: high.

## Re-check after the failure rule (2026-11-16)

Origin line checked: the owner's failure rule (origin file, last section). D7 and FR-005 now require the command's
own exit status for a failure as well as a pass; SC-1 has the `| grep` case; the yield fact adds the recount (249
failures, 1 pair). The yield decision is not made and the spec states none.

Verdict: aligned
Confidence: high
The yield sentence is quoted verbatim in the origin file. Verdict: aligned. Confidence: high.

## Re-check after the yield decision (2026-11-16)

Origin line checked: the owner's yield decision (origin file, last section). D8 records it; FR-012 requires the
README (and CHANGELOG) to say the extractor captures rarely, with the numbers, and that S3 adds the extractors with
real yield. No decision remains open.

Verdict: aligned
Confidence: high

## Re-check after R1–R6 (2026-11-16)

Origin lines checked: #134 requirement 2 ("only after its extracted records are durably stored"), requirement 3
("neither loses nor duplicates a signal"), and the owner's go on the review (origin file, last section).
- R1 (no content dedup for captured records), R2 (key on `tool_use_id`), R3 (one capture at a time) and R5 (a
  readable file without the session is a miss) make requirements 2 and 3 hold where the draft did not.
- R2 amends D1's key element, by the owner's decision; plan.md's `origin_claim` keeps the issue's words ("record
  UUID") as the origin, and D1 records the amendment.
- R4 (per-session cap dropped and counted) and R6 (no capture without locking) are within D3 and D2.

Verdict: aligned
Confidence: high

## Re-check after R7–R9 (2026-11-17)

Origin lines checked: #134's "The #120 count then uses the adapter instead of its own copy" and "How captured
records feed the #120 count", and the owner's message of 2026-11-17 (origin/2026-11-17-owner-diade.md, items 2
and 3), added to plan.md's transcripts with DIADE's report as a URL.
- R7 (subagent files and sidechain lines for the count only), R8 (repeats only from FR-005 failures, the command
  in the evidence) and R9 (multi-word stored errors) are the owner's fixes to the count S2 moves onto the adapter.
- The order note records item 3.

Verdict: aligned
Confidence: high

## Re-check after R10–R11 (2026-11-17)

Origin line checked: the owner's decisions items 1–2 (origin/2026-11-17-owner-diade.md, last section) and #136's
items 3 and 5. R10 and R11 are the two review notes the owner approved; FR-011's README list now matches #136
item 5.

Verdict: aligned
Confidence: high

## Re-check after the review of `0138a5f` (2026-11-17)

Origin lines checked: the owner's review (origin/2026-11-17-owner-diade.md, last section). R12 makes R10 buildable
and keeps recalls with their thread; R13 records the R1 side effect; the order note now lands DIADE's fixtures with
the build; "which the S2 build fixes"; R9 and R11 wording as the owner wrote. No change to what #134 asks for.

Verdict: aligned
Confidence: high

## Re-check after R14–R15 (2026-11-17)

Origin line checked: the owner's go on the review of `d17b407` (origin/2026-11-17-owner-diade.md, last section).
R14 removes the R10/R12 contradiction; R15 makes the count read all 226 local agent transcripts (114 of them
workflow agents the earlier path missed) and corrects the checked fact. No change to what #134 or #136 asks for.

Verdict: aligned
Confidence: high

## Re-check at the build (2026-11-17)

The spec was approved by the owner's merge of #135 (`ddb4b08`); plan.md and spec.md now say so, and tasks.md is
ticked for the build in #137. The build implements FR-001–FR-012 and R1–R15; the review of #137 at `a152074` found
five defects (pre-failure evidence, captured subagent repeats, the metadata-only lookup, the deferred count, a
sidechain without an agent id). The first fix for the last (a shared fallback id) still merged unrelated agents, per
the owner's second review; it now fails closed: a sidechain entry with no agent identity is skipped. All five are
fixed against the spec as written. No change to what #134 or #136 asks for.

Verdict: aligned
Confidence: high

## Re-check after R16 (2026-11-17)

Origin line checked: the owner's decisions on the review of #137 (origin/2026-11-17-owner-diade.md, last section).
R16 replaces FR-006's long-string rule with the owner's per-piece rule; it keeps D4's best-effort statement and
makes FR-011 hold for captured errors that name a long path. No change to what #134 or #136 asks for.

Verdict: aligned
Confidence: high

## Re-check after R16's path-shaped rule (2026-11-17)

Origin line checked: the owner's review of #137 at `cb362cf` (origin/2026-11-17-owner-diade.md, last section).
R16 now splits only path-shaped tokens; the AWS sample key is redacted again and both of the owner's example paths
stay whole. Dashed UUIDs stay redacted, as the owner decided. No change to what #134 or #136 asks for.

Verdict: aligned
Confidence: high

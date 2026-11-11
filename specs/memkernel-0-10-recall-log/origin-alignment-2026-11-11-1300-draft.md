# Origin alignment check — memkernel-0-10-recall-log, the draft spec

Origin: gosha70/memkernel#120 (origin/2026-11-11-issue-120.md), with the counting rule from #112.

Origin claim:
> A recall log (each recall appends time, query, filters and returned ref_ids; under MEMKERNEL_STATE_DIR; off by
> default via a new setting; bounded; no change to recall or the MCP tools) and a counting script in eval/ that
> applies #112's three-step rule, classifies each repeat (returned before the failure, retrieval miss, not in a
> readable store) and states its limits; README section; no mistake type, no model judge.

Working claim:
> FR-001–FR-004: an opt-in, size-rotated JSONL recall log written at the MCP tool and the session-start hook, with
> the fields #120 lists plus origin and the hook's session id. FR-005–FR-007: eval/repeat-mistakes/count.py with a
> temporary Claude Code transcript reader, the rule made mechanical (D5), classes D6, README and CHANGELOG.

Mismatches:
  - Session linking uses the transcripts, not the spool #120 names: the spool is drained at each startup, so its
    windows do not survive to the count (checked in session_spool.drain). Same purpose, a working source.
  - D1 (recommended) logs the MCP tool and the hook, not library callers of MemoryService.recall. Every recall a
    coding session can make is covered; the alternative in D1 covers library callers too. The owner decides.
  - SC-3 adds a fourth fixture case (unknown: no recall records) to #120's three; an addition, not a change.

Verdict: aligned
Confidence: medium

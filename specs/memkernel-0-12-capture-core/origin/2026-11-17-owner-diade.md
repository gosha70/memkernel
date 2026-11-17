# Origin: the owner's message of 2026-11-17 on DIADE's report (verbatim, items 2 and 3)

DIADE's report: https://github.com/gosha70/memkernel/issues/112#issuecomment-6940516688

> 2. Fix #135's spec before it's built, so it doesn't keep the bugs:
>    * FR-004: the count must also read subagent transcripts. That means the subfolder files plus their sidechain
>      lines, so the reader needs a way to include sidechain lines just for the count.
>    * FR-011: a repeat counts only when the run failed under FR-005's definition, and each repeat's evidence names
>      the command.
>    * The fix for single-word signatures fits there too, since FR-005 already moves `ERROR_WORDS` into `src/`.
> 3. Order: DIADE's tests should land before or with S2. FR-004 already says the count's fixture test must keep
>    passing through the move, so their fixtures would then guard the new reader too. A PR against the current
>    `transcripts.py` alone would clash with S2 moving that file.

## The owner's decisions later on 2026-11-17 (verbatim, items 1–4)

> 1. File the issue as drafted: yes. "Dropped" is right because it matches R9. Reporting single-word signatures
>    separately would add code for noise nobody wants to read.
> 2. Add both review notes to the spec: yes. They're small and keep the report honest.
> 3. DeepSeek: push without it now, and run it before merge. The origin gate passes, and I review the full spec on
>    #135 once it's pushed. Waiting on the missing profile only delays that review. Make it a condition that
>    DeepSeek runs once you restore `providers.toml`, before #135 merges.
> 4. Commit and push R1–R9 to #135: yes, once item 2 is in, so I review one complete version.

The two review notes became R10 (subagent repeats reported apart) and R11 (multi-word code fragments in "What it
cannot detect"). The issue is #136.

# Origin note: start memkernel's Release B bridge work (2026-10-26)

The repository owner, 2026-10-26, after seeing wiki-studio's "memkernel Release B loop" CI job red:

> now it is urgent to fix this issue becasue it affects the Wiki Studio CI: https://github.com/gosha70/memkernel/issues/48

Told that the job is non-blocking by design (wiki-studio run 40430968864 concluded success; the loop job has
`continue-on-error`), that memkernel `main` is frozen until its `v0.5.0` tag, and that approved-only import
needs wiki-studio 0.7.0, the owner forwarded wiki-studio's session's advice: start the snapshot removal on a
branch now; the loop job turns green only after wiki-studio's CI moves to the memkernel commit with the fix.

Earlier owner decisions this work implements (memkernel #48 comments of 2026-10-24 and 2026-10-25): remove the snapshot and
scaffold through `api.init`; same cycle, snapshot removal by week 2 and approved-only import by week 5; a
memkernel-owned `corrects` key whose grammar memkernel defines.

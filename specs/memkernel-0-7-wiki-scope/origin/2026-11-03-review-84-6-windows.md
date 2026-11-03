# Origin note: the fifth review of #84 and the owner's Windows decision (2026-11-03)

The fifth review, as pasted by the owner on 2026-11-03. Its findings:

1. [P1] Distinct `EphemeralClient` objects share one underlying store but would get different locks (reproduced
   on chromadb 1.5.9). Key by the shared system, tenant, database and collection, or by collection process-wide.
2. [P1] Injected persistent clients have no canonical lock identity: prohibit them, require an explicit identity,
   or validate their path. Test two processes injecting clients for one directory.
3. [P2] `msvcrt.locking` is not indefinitely blocking; a fake module can't validate it; a real Windows contention
   test is needed.
4. [P2] `promote` still creates a legacy wiki candidate: strip all wiki-import ownership tags or refuse; the test
   must run a following import.
5. [P2] `update_metadata` can bypass the only-tag-writer invariant: reject a `tags` key; test the refusal.

Its recommendation: split S8 into a prerequisite spec and PR. (Not decided by the owner yet; S8 stays in #84.)

A Windows recommendation pasted on 2026-11-03 right after the question was asked, quoted below. **Correction
(2026-11-03):** this was first recorded as the owner's decision. The owner's next paste says "the Windows decision
wasn't mine: it came from another review pass or from you". It is a review pass's recommendation, not yet
confirmed by the owner:

> Choose 4: fail closed for wiki identity, preserve ordinary Windows behavior.
> - On Windows/non-POSIX, wiki_import refuses before any write.
> - set_wiki_identity and retain(wiki_identity=...) refuse.
> - merge_tags may run unlocked only for records without wiki-path: or wiki-id:.
> - If the target already has an identity tag, merge_tags refuses rather than risking its loss.
> - Document wiki import as POSIX-only until a real Windows contention test exists.
> This preserves normal Windows retain/dedup behavior without claiming unverified isolation or breaking every tag
> merge. A later Windows-tested locking implementation can remove the restriction.

The spec answers them in S8 (lock identity, `update_metadata`, `promote`, platforms), FR-007, FR-008 and SC-8.

DeepSeek round 3 (2026-11-03, on the changes since round 2): PASS, 0 blocking. Applied: a page carries exactly one
`reason` (S4, by S3's order); `dedup_owner` is a pure, non-raising predicate called per matching record (S2).
Not applied: repeats of earlier notes (a mechanical owner gate, more detail for the gates task, governed vs
ungoverned importability, the S5 heading), and re-importing a moved wiki from its old path after a partial retag,
which S6 already defines (the directory imported is the wiki's current path; the retag is idempotent).

DeepSeek round 4 (2026-11-03, on the tags-writer and attribution changes): PASS, 0 blocking. Applied: the
owner-decision marker separates the Windows recommendation from the spec changes; S6 says a wiki's own memories
are never a conflict for it and its retag runs before the conflict check. Not applied: repeats of earlier notes.

# Origin note: every planned write, unusable planned_writes, and an uncertain outcome (2026-10-28)

Found by the review of PR #55 at `9200bdc`, and reproduced against wiki-studio 0.6.0:

1. With the page written, the `index.md` write failed and the page's rollback failed, the receipt stayed
   `committing` with the page at its `post_sha256` and the index not. FR-009 checked only memkernel's pages, so
   the export was reported as gated and written; the hint's command then exited 10 with `uncertain_outcome`.
   wiki-studio's own classifier (`promoter._classify_committing`) calls a `committing` receipt committed only
   when every planned write is at its post state, rolled back only when every one is at its pre state, and
   uncertain otherwise.
2. With `planned_writes: []` the page was committed but reported as `gate_error`, with no `receipt_error`: an
   empty or malformed `planned_writes` was taken as usable, so FR-009's content fallback never ran.
3. After a commit and a failed receipt rewrite, another writer appended to `index.md`; the hint's command, which
   FR-005 said "finishes the archive and applies nothing twice", exited 10.

The owner's decision, 2026-10-28:

> open the spec-only PR amending FR-005 and FR-009 with an alignment record. Include the case where a committing
> receipt's pages are at post_sha256 but another planned write isn't: report it as an uncertain outcome (pages
> may be on disk; compare with receipt.json), not as "no page was written".

This amends FR-001's exception sentence, FR-005 (the hint is a recovery attempt), FR-008 (the
`uncertain_outcome` key), FR-009 (the classification and the uncertain outcome) and SC-7.

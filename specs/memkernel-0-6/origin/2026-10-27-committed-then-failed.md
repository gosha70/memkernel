# Origin note: an export wiki-studio committed and then failed (2026-10-27)

Found by the review of the part 1 code (PR #55, commit 96a9297) and reproduced: wiki-studio 0.6.0 committed the
page, then failed to rewrite its receipt as committed ("the edits were committed to the wiki … Promote the
directory again to finish"); memkernel reported `written: []`, `skipped: 1` and "gate rejected the export" while
the page was on disk.

The owner's decision, 2026-10-27, on the choice between detecting it and documenting it:

> A2: detect it, with the spec amendment first. Detection has a better basis than the content check you
> proposed. When wiki-studio fails after committing, it has already written a receipt in state `committing`, with
> the planned writes and their expected hashes after the write. Check that each planned page's on-disk sha256
> equals the receipt's post-write hash. That's wiki-studio's own record of what it meant to write, rather than
> memkernel's guess. Fall back to comparing content only if the receipt can't be read. Report it as written, with
> `archived_dir: null` and the "promote again" hint. Don't retry automatically: running promote again is the
> user's step, as the hint says.

The re-review of the first implementation found a false positive, reproduced: with no receipt at all (wiki-studio
refused a create of an existing page before step 1) and another export's identical page on disk, the content
fallback reported a commit. The owner's decision rests on "it has already written a receipt in state
`committing`", and wiki-studio's own rule is that a missing receipt is never taken to mean a commit; so a missing
receipt means no commit, and the content fallback applies only to a receipt that exists but cannot be read, as
the decision says. The owner confirmed the decision as worded on 2026-10-27.

This becomes FR-009 and SC-7. The same review moved the archive hint to absolute paths (FR-005).

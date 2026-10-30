# Origin alignment check — memkernel-0-7 (Release B part 2b)

Origin: https://github.com/gosha70/memkernel/issues/48, wiki-studio's Release B pitch, and specs/memkernel-0-7/origin/2026-10-30-part-2b.md.

Origin claim:
> "Withdrawal on supersession, deprecation and explicit deletion; a pending / applied / failed synchronisation state with a retry path; no claimed transaction across Markdown and the memory store." (2026-10-30) Check wiki-studio 0.7.0 and 0.8.0 for deletion and deprecation signals; weigh withdraw as a new marker vs a tombstone record, and sync state as tags vs a ledger in memkernel's store directory; recommendations for the owner to confirm.

Working claim:
> wiki-studio 0.7.0 and 0.8.0 report supersession, deprecation only as frontmatter, and no deletion, so memkernel detects deletion from a complete review_state listing plus the file's absence. A new withdrawn marker (one liveness predicate, metadata default) is recommended over a tombstone record and a sentinel; a per-project ledger in the store directory is recommended over tags. Superseded pages are superseded by the successor's memory when it exists, else withdrawn and linked later; deprecated pages are withdrawn. The governed import does this through the ledger with retry; no transaction is claimed. Decisions D1–D5 are open for the owner to confirm before build.

Mismatches:
  - none. Every element of the origin claim is a requirement, and the owner's two weighings are in the spec with recommendations. Part 2c is left to its own spec.

Verdict: aligned
Confidence: high

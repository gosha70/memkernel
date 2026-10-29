# Origin note: one memory per page, and a partial supersession repaired on retry (2026-10-29)

A review of PR #60 at `b2a47ec` reproduced two defects:

1. `_retain_page` imports through `retain`, which deduplicates by content and type. Two approved pages with
   different paths, slugs, keys and sha256 values but identical title and body collapsed into one record. Editing
   one page superseded that shared record, and the other page was reported `unchanged` while it had no live
   memory. The PR had listed this as a known limitation; the review showed it breaks FR-012's page identity and
   FR-013's preservation of approved memories.
2. `_mark_superseded` marked the record before its owned chunks, and `supersede` returned `False` as soon as the
   record carried the marker. With a failure on a chunk update, the record was marked, the chunks were not, and no
   retry repaired them; the importer also skipped the call for a correction already in effect. FR-017 requires
   the marker on the record and its owned chunks.

The owner's decision, 2026-10-29. The owner accepted the reviewer's plan (spec-only PR first, dedup scoped to the
page's source, the importer's re-call using the existing marker) and changed the rule for a shared record:

> go: both. In the spec draft, the origin note quotes this message, not the reviewer's text. Change the
> shared-record rule: the record belongs to the page whose path is its source; only that page's new revision may
> supersede it; any other page whose page_key tag it carries gets its own record. Test both edits (the other page
> edited, and the source page edited).

This amends FR-012 (one memory per page), FR-017 (the chunk-first mark, the retry repair, `retain`'s
`dedup_source`), the core constraint, and SC-9.

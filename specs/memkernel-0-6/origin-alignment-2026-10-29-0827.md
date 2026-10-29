# Origin alignment check — memkernel-0-6, FR-012 one memory per page and FR-017 retry repair (review of #60 at b2a47ec)

Origin: https://github.com/gosha70/memkernel/issues/48 (and its owner-decision comments of 2026-10-24 and 2026-10-25), https://github.com/gosha70/wiki-studio/issues/38, wiki-studio's Release B pitch, and the origin notes under specs/memkernel-0-6/origin/, including 2026-10-29-page-identity.md.

Origin claim:
> Close the memkernel side of wiki-studio's Release B (memkernel #48): ... import approved revisions only and reconcile corrected memories once wiki-studio 0.7.0 provides review state. (2026-10-29) "Change the shared-record rule: the record belongs to the page whose path is its source; only that page's new revision may supersede it; any other page whose page_key tag it carries gets its own record. Test both edits (the other page edited, and the source page edited)." With the reviewer's plan accepted: dedup scoped to the page's source, the importer's re-call using the existing marker.

Working claim:
> FR-012 now requires one memory per page: the importer deduplicates only against records with the page's source, through retain's new keyword-only dedup_source. A record carrying more than one page_key tag belongs to the page whose path is its source; only that page's new revision supersedes it, and every other page whose key it carries gets its own record. FR-017 marks owned chunks before the record, repairs unmarked chunks on an idempotent call, and has the importer re-call supersede with the existing marker. SC-9 gains the matching tests, including both edits of a shared record.

Mismatches:
  - none. The amendment implements the owner's 2026-10-29 decision as worded; it adds one keyword-only option to retain (default unchanged) and no port change.

Verdict: aligned
Confidence: high

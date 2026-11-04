# Origin alignment check — memkernel-0-7-governed, the US1 build

Origin: as in origin-alignment-2026-11-04-0736-approved.md, plus the owner's message of 2026-11-04: "Just made the
doc changes in the next PR - forget about the merged one. And start building - go". The doc change is the Decisions
heading of spec.md, now "confirmed by the owner on 2026-11-04; revised after review".

Origin claim:
> Release B part 2c for #48: a governed configuration that requires the gate and checks capabilities and the
> manifest's approval_required, an identified ungated mode, curation debt at session start, bounded candidate
> batches, source content hashes with git revision metadata, the bridge's checklist items and the page_id opt-in.

Working claim:
> Built as G1–G6: MEMKERNEL_WIKI_MODE with the governed preflight on export and import and `mode` /
> `configured_mode`; the curation debt section in a spawned child bounded to 2.5 s with the read-only ledger
> snapshots; MEMKERNEL_WIKI_EXPORT_BATCH and `remaining`; `sha:` and `memkernel_sha256`; `assign_page_ids=True`;
> README notes on the lock file and `hash_recipe`.

Mismatches:
  - G5 assumed "a later rename keeps the page's memory" already. The real wiki-studio test showed it does not: a
    page renamed under its page_id kept its content, so the import found no dedup hit at the new path and wrote a
    second live memory. SC-5 needs the fix, so the import now also supersedes when the previous memory, found by
    page_key, is at another path (sync.py, one condition). For the owner to confirm.
  - SC-1 says every existing test passes unchanged. Three test helpers changed because gated pages now carry a
    page_id (G5): a copied twin page drops it, a hand-made duplicate record uses the page's key, and the
    gated-versus-direct comparison ignores the page_id line and asserts it is present. No assertion was weakened.
  - G2 does not say where the in-memory snapshot gets the ledger key, which needs the manifest's wiki_id that
    only the child reads. The child returns the key; the parent copies the in-memory counts after the child,
    under the same deadline taken before the start.

Verdict: aligned
Confidence: medium

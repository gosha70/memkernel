# Origin alignment check — memkernel-0-7-governed

Origin: gosha70/memkernel#48; wiki-studio's Release B pitch (memkernel counterpart); specs/memkernel-0-7-governed/origin/2026-11-03-part-2c.md.

Origin claim:
> "A governed configuration that requires the gate, refuses the unchecked fallback writer, and checks info capabilities and the manifest's approval_required; an identified ungated mode." "Curation debt at session start (from S6), bounded candidate batches, source content hashes with git revision metadata." The bridge-only checklist items (receipts, lock file, hash_recipe) and the page_id opt-in. The owner: "Then the Release B 2c spec."

Working claim:
> MEMKERNEL_WIKI_MODE (auto default, governed, ungated): governed requires a working wiki-studio >= 0.7.0, the capabilities the bridge uses, a manifest in governed mode and no drift, before any page write or read, and never uses the direct writer; ungated never loads wiki-studio. A curation debt section at session start from api.findings counts and the ledger's unfinished entries, within a 500-character share taken from the context share. MEMKERNEL_WIKI_EXPORT_BATCH (default 10) with remaining. sha: on clean tracked path sources and memkernel_sha256 on exported pages. assign_page_ids on gated exports. README notes for the lock file and hash_recipe; receipts already consumed.

Mismatches:
  - none against the origin. Every item of the pitch's memkernel counterpart not built in 2a/2b is a decision here. The decisions are recommendations: the owner gave no weighing for 2c.

Verdict: aligned
Confidence: medium

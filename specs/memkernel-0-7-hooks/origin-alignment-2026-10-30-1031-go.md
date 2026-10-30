# Origin alignment check — memkernel-0-7-hooks, the owner's go of 2026-10-30

Origin: as in the previous records, plus the owner's go of 2026-10-30:

> go: push both amendments to #76 and #77 (no force-push). Before pushing: hash the wiki path relative to the project root (and note that a manifest wiki_id makes the key stable); resolve MEMKERNEL_STATE_DIR like the Chroma persist path, add it to the README configuration table and a gitignore note; in H4 take each session's window from its first started to its last ended, and say that SessionStart writes the started line on resume and fork too.

Working claim:
> H4: SessionStart writes a started line for every source, resume and fork included; a session's window runs from its first started line to its last ended line, so a resumed session is one window (FR-009, SC-7). The spool's MEMKERNEL_STATE_DIR defaults to .memkernel/state and resolves like the Chroma persist path; whichever spec is built first adds the setting, its README row and the gitignore note.

Mismatches:
  - none. The wiki-key point applies to memkernel-0-7.

Verdict: aligned
Confidence: high

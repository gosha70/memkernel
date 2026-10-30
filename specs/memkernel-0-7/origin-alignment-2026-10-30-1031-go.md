# Origin alignment check — memkernel-0-7, the owner's go of 2026-10-30

Origin: as in the previous records, plus the owner's go of 2026-10-30:

> go: push both amendments to #76 and #77 (no force-push). Before pushing: hash the wiki path relative to the project root (and note that a manifest wiki_id makes the key stable); resolve MEMKERNEL_STATE_DIR like the Chroma persist path, add it to the README configuration table and a gitignore note; in H4 take each session's window from its first started to its last ended, and say that SessionStart writes the started line on resume and fork too.

Working claim:
> D2's wiki key is the manifest's wiki_id when present (stable across moves of the wiki directory), else the sha256 of the wiki directory's path relative to the project root. MEMKERNEL_STATE_DIR defaults to .memkernel/state and resolves like MEMKERNEL_CHROMA_PERSIST_PATH (relative to the process's working directory); FR-004 and task 5 add its README configuration row and the .memkernel/state/ gitignore note.

Mismatches:
  - none. The H4 points apply to memkernel-0-7-hooks.

Verdict: aligned
Confidence: high

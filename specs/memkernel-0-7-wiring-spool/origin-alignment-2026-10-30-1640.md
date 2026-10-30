# Origin alignment check — memkernel-0-7-wiring-spool (#81 and the #79 spool follow-up)

Origin: https://github.com/gosha70/memkernel/issues/81, https://github.com/gosha70/memkernel/pull/79#issuecomment-6529951075, and specs/memkernel-0-7-wiring-spool/origin/2026-10-30-go.md.

Origin claim:
> Spec for #81 with option C recommended (the wiring check runs both import paths), and the spool-pruning follow-up (sessions without an ended line are never pruned), together as one small spec-only PR.

Working claim:
> The wiring check gains --wiki-path auto|governed|ungoverned|both: governed marks the exported page stable through a promoted update and approves it with wiki-studio, through the server's interpreter (approve refuses a draft); ungoverned hides wiki-studio from the server with a stub package raising ModuleNotFoundError(name="wiki_studio"); both runs the two legs; auto keeps the image's meaning. The 0.5 records are not edited. The spool drain removes unended sessions older than 7 days and says once how many, with a hint to register session-end.py. Decisions W1 and W2 are open for the owner to confirm.

Mismatches:
  - none. Option C is the recommendation, both items are in one spec, and #80 and 2c are left out.

Verdict: aligned
Confidence: high

# Origin alignment check — memkernel-0-7-wiki-scope, after the fourth review of #84

Origin: as in the previous record, plus specs/memkernel-0-7-wiki-scope/origin/2026-11-03-review-84-5.md.

Origin claim:
> #80's acceptance: importing a second wiki with an overlapping path or page_id never supersedes, withdraws or deprecates the first wiki's memory; a single-wiki project behaves as today, legacy memories included. The fourth review: S8's guarantee must hold across supported configurations: locks keyed by the store, a safe non-POSIX branch, identity tags protected from generic tag writes, and an in-memory lock shared by adapters on one client.

Working claim:
> As the previous record, with S8 rewritten: import and tag locks keyed by the resolved persist directory and collection (or, in memory, by the client object and collection); fcntl on POSIX, msvcrt on Windows, fail closed elsewhere; update_metadata sends only the caller's keys (Chroma merges natively) and tags are written only by merge_tags under the tag lock; wiki-path:/wiki-id: are reserved: refused in retain and the MCP tool, set only through retain(wiki_identity=) and set_wiki_identity, and dropped by promote.

Mismatches:
  - S8 continues to reach beyond the wiki import (the storage adapter, retain, the MCP retain tool, promote). Each change closes a path by which identity tags could be lost or forged, so it serves #80's isolation; recorded so the scope growth stays visible.
  - Unchanged: US1 and US2 await the owner's confirmation.

Verdict: aligned
Confidence: medium

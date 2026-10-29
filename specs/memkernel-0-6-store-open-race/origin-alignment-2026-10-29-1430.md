# Origin alignment check — memkernel-0-6-store-open-race (#69)

Origin: https://github.com/gosha70/memkernel/issues/69 and specs/memkernel-0-6-store-open-race/origin/2026-10-29-issue-69.md.

Origin claim:
> Fix #69: the SessionStart hook and the MCP server open the same new ChromaDB store at once and one fails with "table collections already exists". (2026-10-29) "Weigh options A, B and C, and say which processes the chosen fix protects (the MCP server, all three hooks, the admin API all open the store through build_service). Include #69's three tests and a CHANGELOG entry in the tasks."

Working claim:
> Option B: ChromaVectorStore.__init__ holds an fcntl advisory lock on .memkernel-open.lock in the persist directory while it opens the PersistentClient and gets or creates the collection, releasing it on every path. A is rejected (a working retry must drop chromadb's private or process-wide system cache), C is not built (it only narrows the hook's side). The fix protects every memkernel process that opens a persisted store through build_service: the MCP server, the three hooks, the admin API and library callers; not a caller-supplied client, the in-memory client or a non-memkernel process. Tasks: the lock, the deterministic injected-error test, the slow two-process test with the consistency check, and a CHANGELOG entry.

Mismatches:
  - none. The three options are weighed with measurements, the protected processes are named, and #69's three tests and the CHANGELOG entry are tasks. #69's Option A text assumed a retry would work once the other process finished; the measurement shows it does not without touching chromadb's cache, which the spec records as the reason A is rejected.

Verdict: aligned
Confidence: high

# Origin alignment check — memkernel-0-3

Origin: docs/adr/ADR-009-rlm-studio-for-documents.md (also docs/roadmap.md § "0.3", docs/integration/harness-integration.md § "haa"); all three read in full from the repository this session.

Origin claim:
> Continue memkernel on a 0.3 branch: the DocumentStorePort/ReasonerPort ports, the document memory type, ask(), MemoryLifecycle, plus the two-line artifact-action bump from the release warnings. Implement it the fastest, most automated way using code-copilot-team's unattended build loop with DeepSeek as the code reviewer. RLM Studio is the document layer (owner decision, ADR-009): its Direct / RAG / RLM / auto selection is what "hybrid mode" means for memkernel, passed through unchanged. haa is the future component-assembly harness, so every capability must also exist as a Python component with a small, stable interface, not only as an MCP tool.

Working claim:
> spec.md delivers five user stories: (US1) `DocumentStorePort` and `ReasonerPort` protocols in `core/ports.py`, an `Answer` model, a long-term `document` memory type (importance 0.6) whose body is stored and chunk-indexed through a built-in `LocalDocumentStore` on ChromaDB while the memkernel record keeps a summary; (US2) `MemoryService.ask(ref_id, question, mode)` exposed as the `ask` MCP tool, answered by an LLM-free `LocalReasoner` (hybrid search over chunks, `mode="rag"`), with the `forget_expired` tool removed to keep the tool count at nine; (US3) an `adapters/rlmstudio.py` reasoner that lazily imports `rlmstudio` and calls `interact(content, question, mode=mode)` with the mode string passed through unchanged, falling back to the local reasoner with a warning, plus `consolidate(synthesize=True)` through the reasoner; (US4) a `MemoryLifecycle` Python component (`on_session_start`, `on_pre_compact`, `on_post_compact`, `on_session_end`) that the three hook templates wrap thinly, so haa can assemble the same behaviour in-process; (US5) version 0.3.0, CHANGELOG, README, `release.yml` bumped to `upload-artifact@v5` / `download-artifact@v6`, ADR-009 marked accepted. No new runtime dependency; `rlm-studio` is documented as a git install rather than a packaged extra.

Mismatches:
  - none

Verdict: aligned
Confidence: high

Notes (explicitly deferred by the approved spec, not drift from the user's claim):
  - ADR-009 and the roadmap mention a `memkernel[rlm]` extra; FR-016 defers it because `rlm-studio` is not on PyPI and documents the git install path instead. The user's origin claim does not require the extra.
  - The roadmap's sentence-transformers `EmbeddingPort` shim is an upstream contribution to rlm-studio and the `procedure`-as-skill item is a separate feature; the spec's "What NOT to Build" section excludes both.
  - `on_session_end` returns `str` in the spec (harness-integration.md says `-> None`); the spec's return value is a superset that haa can ignore.

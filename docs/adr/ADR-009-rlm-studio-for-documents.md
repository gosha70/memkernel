# ADR-009: RLM Studio is the document layer; memkernel asks questions of documents instead of loading them

Status: accepted (2026-10-11). Implemented in memkernel 0.3 (`specs/memkernel-0-3`); the "hybrid mode" reading below is the owner's.

## Context

memkernel stores *memories*: short, typed, scored records. It also stores
`code` snapshots and, via the wiki bridge, whole pages. The owner wants
**RLM Studio** (`gosha70/rlm-studio`, MIT, 1.0.0rc1) adopted as the system
that manages and stores documents, data and information, in particular its
"hybrid mode".

What RLM Studio provides (surveyed from `master`, 2026-10-01):

- **Three execution modes plus `auto`** — `direct` (whole content in the
  prompt), `rag` (chunk, embed, retrieve top-k, answer), `rlm` (content bound
  to a sandbox variable `P`; the model explores it with `peek/grep/chunk/
  outline_file/subcall` and never sees it whole), and `auto`, which picks
  `direct` under 8K tokens and `rlm` above. `compare` runs any mix across
  providers. **This per-run Direct / RAG / RLM / auto selection is what this
  ADR takes "hybrid mode" to mean.** If the owner means something else (for
  example RAG-seeded RLM exploration), the integration surface below does
  not change, only the default `mode` passed through.
- **`StoragePort`** (`application/ports/storage_port.py`): conversations,
  `save_file_context(content, filename) -> content_hash` (deduplicated),
  `get_file_context(hash)`, `add_chunks(collection, chunks, embeddings,
  source_id, metadata)`, `search_chunks(collection, query_embedding, top_k)`.
  SQLite adapter today; the port is backend-neutral.
- **`EmbeddingPort`** (`embed(str)`, `embed_batch(list[str])`, `dimension`)
  with a LiteLLM adapter; its own docstring says it "will be superseded by
  rag-core's embedder once rag-kit reaches v0.1.0".
- **Public API**: `rlmstudio.interact(content, query, mode=...)`,
  `interact_async`, `compare_matrix`, `rlmstudio.public.RLMKitClient` with
  a `mock` provider for tests; budgets (steps, tokens, cost, time), traces,
  replay, telemetry.
- **File ingestion**: `/api/files/upload` extracts text from PDF/DOCX/text,
  cleans PDF boilerplate, stores by hash; chat routes resolve `file_ids`
  and index them once per file set for RAG.

The problem memkernel has that RLM Studio solves: `get(ref_id)` returns
full content. For a 2,000-line file, a long transcript or a 40-page spec
that is exactly the context blow-up the agent was trying to avoid. The
agent needs to *ask a question of* a large artefact, not read it.

## Decision

1. **Two stores, one index.** RLM Studio's `StoragePort` becomes the home of
   *documents* (files, specs, PDFs, transcripts, uploaded data): immutable,
   hash-deduplicated, chunk-indexed. memkernel's store keeps *memories*, and
   a memory that refers to a document carries `source="rlm://<content_hash>"`
   plus a short summary as its content. `recall` still finds it (the summary
   and tags are embedded); the body lives in RLM Studio.
2. **A new memory type `document`** (long-term tier, importance 0.6):
   `retain(type="document", content=<full text or path>, source=<name>)`
   stores the body through the document port, indexes its chunks (RLM
   Studio's `IndexedRAGStrategy.index_content` path), and keeps a memkernel
   record whose content is the first ~1,000 characters plus a generated
   outline. `get` on a `document` returns the summary and the `rlm://` id,
   never the body.
3. **A new MCP tool `ask(ref_id, question, mode="auto")`**: resolves the
   memory's document (or, for any non-document memory, its own content),
   calls `rlmstudio.interact(content, question, mode)` and returns the
   answer, the mode actually used, token/cost usage and the trace id.
   `mode` passes straight through (`direct | rag | rlm | auto`). This is
   the "hybrid" entry point: the agent chooses, or lets `auto` choose,
   between reading, retrieving and recursively exploring.
4. **Ports, not imports, in core.** memkernel adds two protocols in
   `core/ports.py`: `DocumentStorePort` (`put(content, name) -> doc_id`,
   `get(doc_id)`, `index(doc_id)`, `search(doc_id | collection, query,
   top_k)`) and `ReasonerPort` (`ask(content, question, mode) ->
   Answer`). The RLM Studio adapter lives in `memkernel/adapters/rlmstudio.py`
   and is shipped as the optional extra **`memkernel[rlm]`**, because
   `rlm-studio` imports LiteLLM at import time. Without the extra, `document`
   falls back to memkernel's own store (chunked via `ASTChunker`/token
   splitter) and `ask` answers with `mode="rag"` over memkernel's hybrid
   search, returning the top chunks instead of a synthesised answer.
5. **Consolidation can use the reasoner.** When `ReasonerPort` is
   configured, `consolidate(synthesize=True)` asks RLM Studio to distil a
   session's short-term memories into candidate long-term statements
   (Letta-style sleep-time compute). Default stays `False`: the agent is
   the synthesiser unless the harness opts in.
6. **Give back the embedder.** memkernel contributes a sentence-transformers
   adapter satisfying RLM Studio's `EmbeddingPort` (a 20-line shim over
   memkernel's `EmbeddingPort`, which embeds lists) so RLM Studio's RAG
   mode can run fully local, and later the `HybridSearchService` behind
   its `StoragePort.search_chunks`. This is the "rag-core" its docstring
   anticipates, until the new `ragkit` exists (ADR-008, sibling-projects).

## Alternatives considered

- **Store documents as `code`/`fact` memories and chunk them.** Works for
  retrieval, fails for "answer this question about the whole spec": the
  agent still has to read every chunk. RLM mode exists for exactly that.
- **Call RLM Studio over HTTP (`rlm-studio studio`).** Keeps memkernel's
  process light, but adds a server to run and a session to manage for
  every hook. In-process `interact()` behind an extra is simpler for the
  single-user harness case; the HTTP adapter can be a second
  `ReasonerPort` implementation later.
- **Move memkernel's memories into RLM Studio's SQLite store.** Its
  `VectorStore` is a brute-force cosine loop with no metadata filtering, no
  BM25, no tiers. memkernel's store stays.

## Consequences

- MCP surface goes to 10 tools (`ask`), reaching the FR-013 ceiling. Either
  raise the ceiling in the spec or fold `forget_expired` into
  `consolidate(purge=True)` (it already is) and drop the standalone tool.
- New extra `memkernel[rlm]` (`rlm-studio>=1.0.0rc1`); core stays free of
  LiteLLM.
- `templates/claude-memory-instructions.md` gains: "for anything longer
  than a screen, `retain(type=document)` and `ask()` instead of `get()`".
- RLM Studio needs a published release (it is at 1.0.0rc1, not on PyPI);
  until then the extra installs from git.
- Implementation order (roadmap 0.3): ports → `document` type with local
  fallback → RLM adapter + `ask` → embedder shim contributed upstream →
  reasoner-backed consolidation.

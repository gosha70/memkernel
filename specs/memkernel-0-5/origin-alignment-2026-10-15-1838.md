# Origin alignment check — memkernel-0-5

Origin: https://github.com/gosha70/memkernel/issues/17 (read in full this session), the wiki-studio repository and its `docs/consumers.md` at v0.1.0 (read in full), and the user's statements and decisions recorded in specs/memkernel-0-5/origin/2026-10-15-decisions.md.

Origin claim:
> Show strong evidence of how memkernel helps with memory and context management, and state clearly what it is and what it is not (it is not a token optimizer). Adopt wiki-studio as the wiki maintainer where the current release is sufficient (lint and health, shared schema) and specify what wiki-studio must expose for the rest (promote gate, schema as code). Finalize the positioning and the wiki-studio contract before the first benchmark run; let the #17 protocol proceed in parallel.

Working claim:
> spec.md (merged in PR #19 at cc7bde6) delivers four user stories. (US1, 0.4.1) the positioning section and roadmap evidence item already merged in #18 stay as they are; every `ai-wiki` reference becomes wiki-studio; wiki-studio joins the dev group and a contract test proves that `WikiExporter` output lints clean with `wiki_studio.api.lint(health=True)`; CI is untouched because its plain `poetry install` covers the dev group. (US2, 0.5.0) an optional `memkernel[wiki]` extra with ADR-010, lazy import that is silent when absent, lint and health findings returned on `wiki_export` with field-for-field `HealthFinding` shapes and no new tool; the promote gate (`propose` + `promote`, drafts byte-identical to the direct write) and a schema drift test wait for wiki-studio 0.2.0 (wiki-studio#7) with an explicit 0.1 fallback; ingest and query backends are never adopted. (US3, 0.5.0) memkernel enters `agent-memory-bench` at a pinned commit through an adapter that feeds only verbatim transcript bytes as `document` records via the published MCP path, with the document-store mode declared; the harness's own control arms including `fs_grep` serve as the files-only negative control; a supplemental lifecycle suite in the benchmark's task format covers retain across sessions, revalidation after a repository change, wiki sharing and within-session compaction, every group conditional on a harness mechanism task 11 validates; executable grading only, trace-derived diagnostics as counts, a freeze verifier with a hash-locked preregistration, secret scan over published results. (US4, 0.5.0) one preregistered run on a Claude model from a code-freeze SHA, preregistration pushed and announced on #17 before the first session, report with nulls and discarded cells, release and post-tag roadmap ticks.

Mismatches:
  - none. One deliberate method change relative to #17's suggested shape: #17 proposed a blinded LLM judge and metrics such as first-pass approval; the spec uses the public benchmark's executable grading instead and keeps only count-based diagnostics. This was decided in review, announced on #17 in the direction-update comment, and stays inside #17's actual request (reproducible, preregistered, negative control, publish the no-gain cases).

Verdict: aligned
Confidence: high

Notes:
  - Reviewed through eight external rounds before the merge of PR #19; the origin (#17, wiki-studio, the user's four statements) did not change during them.
  - The commit count for the benchmark was corrected in-session (455, not about thirty); the risk statement is to be refreshed when `BENCHMARK_COMMIT` is pinned (task 11).

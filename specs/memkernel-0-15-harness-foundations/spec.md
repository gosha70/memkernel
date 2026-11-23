# Spec: harness foundations, scoped knowledge, context receipts and retrieval observability (#119)

Status: draft, 2026-11-18. The design and plan #119 asks for before any code ("AI Harness produces a design and
implementation plan before coding"). Approved by the owner, 2026-11-19: D1–D6 as written below, with H1 built first.
Drafted overnight on 2026-11-18; nothing here is built yet.

## What memkernel already has (`main` at `4ef72c2`)

| #119 capability | Already in memkernel | Gap |
|---|---|---|
| Exclude superseded, unapproved, irrelevant knowledge (Part 1) | `recall` hides superseded and withdrawn records; code and decisions whose source changed are flagged (`needs_review`) and hidden unless asked (#123); the wiki import takes only approved pages (wiki-studio gate, memkernel-0-7-governed) | none for these |
| Task-, feature- and agent-aware retrieval; private agent memory (Part 1) | one store per `project_id`; a `session_id` filter on `recall` | no notion of an agent or a task; nothing private: every record is visible to every caller of the project |
| Explicit abstention (Part 1) | `recall` returns an empty list; #128 measured an absolute relevance floor and dropped it (A5) | an empty result says nothing about why |
| Versioned, inspectable context; traceability to sources (Part 2) | every record has a `content_hash`; decisions keep their source file's `source_hash` (#123); code records their file; wiki pages their path and page hash | no record of which memories, at which hashes, a given run received |
| Awareness of changed, stale, missing, superseded knowledge since a run (Part 2) | revalidation flags changed sources; supersede chains (`superseded_by`) | no comparison of an earlier run's context with the store now |
| Correlation of retrieval with runs, tickets, agents (Part 3) | the recall log (#120, opt-in): time, origin, session, query hash, filters, returned `ref_id`s, per recall and per hook block | no run, ticket or agent id; no latency, size or excluded counts |
| Effectiveness against baselines (Part 3) | the repeated-mistake count (#120, #136); the 0.5 lifecycle evaluation (#17) | nothing per run or agent |
| Telemetry integration (Part 3) | none; OpenTelemetry is only a transitive dependency (through chromadb) | a direct use needs an ADR (no new runtime dependency without one) |

**Constraints that shape the design:** the MCP tool set is pinned below ten and has nine tools
(`test_tool_count_under_10`), so at most one new tool; ChromaDB metadata is scalar only, and every new key must load
with a default from older stores (CLAUDE.md); `core/` depends only on ports.

## User Scenarios (#119's success scenarios)

1. Two agents work on different features of one project. Both recall the project's approved decisions; neither
   recalls the other's private task notes.
2. After source code or a decision changes, the harness compares the context an earlier run received with the store
   now, and sees which memories changed, were superseded, went missing or were flagged.
3. The harness can say which memories were supplied in a run, how long retrieval took and how much context it
   added, and correlate that with the run's outcome and repeated mistakes.

## Requirements

- **FR-001 Scope (Part 1, D1).** A record has a `scope`: `project` (the default, shared, as today), `agent:<id>` or
  `task:<id>`. `retain` takes `scope`; `recall` takes the caller's `agent` and `task` and returns `project`
  records plus records of that agent or task, never another's. Records from older stores load as `project`.
  - **Every read path applies it,** not only `recall`: `get`, `list_memories`, `ask`, `consolidate`'s promotion
    candidates, wiki export drafts, and the hook blocks (session start, compaction recovery, `on_post_compact`). A
    caller without an agent or task sees `project` records only.
  - **Promotion keeps the source's scope.** Promoting an `agent:` note gives an `agent:` long-term memory; making it
    `project` is an explicit `scope` argument, never a default, so promoting cannot publish a private note.
  - **Convention, not security.** The caller names its own agent and task ids (D6), so any client can claim any id.
    Scope keeps agents from tripping over each other's notes; it does not keep a hostile client out. The README
    says so.
- **FR-002 Correlation (Part 3, D2).** A run, agent and task id reach memkernel per call (`recall` and `retain`
  arguments) or per process (`MEMKERNEL_RUN_ID`, `MEMKERNEL_AGENT_ID`, `MEMKERNEL_TASK_ID`), a call's value winning.
  They are written into the recall log and onto retained records (`run_id`, as provenance).
- **FR-003 Context receipt (Part 2, D3).** With the recall log on, each record also lists, per returned memory, its
  `content_hash`, its source and source hash where it has one, and its state (live, flagged); plus the recall's
  latency, returned characters, and how many candidates were excluded by each filter (superseded, flagged, expired,
  out of scope). The receipt is the context a run received.
- **FR-004 Context diff (Part 2).** `eval/context-diff/diff.py` (a maintained eval tool, like the count) takes a
  run id and reports, for each memory in that run's receipts: unchanged, changed (another `content_hash`),
  superseded (and by what), missing (deleted or expired), flagged now, or source changed (`source_hash` no longer
  matches the file).
- **FR-005 Abstention (Part 1).** When a `recall` returns nothing, the reason (nothing stored for the filters,
  everything matching was superseded or flagged, or nothing in the caller's scope) goes into the recall log's
  receipt, not into the response. MCP `recall` returns a JSON list today, and existing clients parse a list, so the
  response stays unchanged.
- **FR-006 Effectiveness (Part 3).** The repeated-mistake count groups its report by run and agent when the log
  has them. The comparison against simpler approaches reuses the lifecycle suite (#90, #17); this spec adds no new
  evaluation runner.
- **FR-007 Docs.** README "Using memkernel from a harness": scopes, correlation, receipts, the diff tool, limits.

## Constraints / What NOT to Build

- No orchestration, agent composition or end-to-end tracing: those are the harness's (#119's boundaries).
- No new MCP tool (the scope and correlation arguments go on `recall` and `retain`); no graph database; no MemoryView
  API or Knowledge Pack format.
- No OpenTelemetry in this work (D4).
- Wiki approval stays wiki-studio's.

## Key Entities

- **Scope:** who may recall a record: the project, one agent, or one task.
- **Receipt:** the recall-log record of what one recall returned, with hashes, states and exclusions.

## Success Criteria

- **SC-1** Two agents' private records are invisible to each other through every read path (`recall`, `get`,
  `list_memories`, `ask`, the promotion candidates, wiki export, the hook blocks); both get the project's records;
  promoting an `agent:` note keeps its scope (FR-001).
- **SC-6** An empty recall's reason is in its receipt, and the MCP `recall` response is still a JSON list
  (FR-005).
- **SC-2** A run's receipts, after a decision is superseded and a source file changes, diff as superseded and source
  changed (FR-003, FR-004).
- **SC-3** The recall log carries run, agent and task ids, latency, size and exclusion counts (FR-002, FR-003).
- **SC-4** Older stores load with every record in the `project` scope; existing callers see no change.
- **SC-5** Fast suite, ruff, mypy strict, coverage ≥ 80%; the MCP tool set unchanged.

## Decisions (the owner's, 2026-11-19)

- **D1 Scope as a metadata field** (`scope`), filtered at recall, rather than a collection per agent or task.
  One store keeps project knowledge shared without copying it, and old records need only a default.
- **D2 Correlation per call and per process:** arguments on `recall` and `retain`, and environment variables for a
  harness that starts one server per agent.
- **D3 Receipts in the recall log** (opt-in, as now), not a second store.
- **D4 No OpenTelemetry now:** the ids in the log are what a harness's own tracing joins on; a direct dependency
  would need an ADR.
- **D5 Three slices**, each its own spec amendment and build PR:
  - **H1, receipts and correlation** (FR-002, FR-003, FR-006): it extends the recall log, changes no retrieval, and
    gives the measurements the other two need.
  - **H2, scope and abstention** (FR-001, FR-005): the data-model change.
  - **H3, the context diff** (FR-004).

  Order: **H1 first** (the owner: it changes no retrieval and gives the measurements the other two slices need), then
  H2, then H3. #119 asks that the three areas be evaluated together, which this spec does; it leaves the number of
  PRs to the plan.
- **D6 Who decides an agent or task id:** the caller (the harness), never memkernel.

## Amendment H1: receipts and correlation (approved by the owner, 2026-11-23)

The H1 build (D5) as it will be built; nothing in H2 or H3 changes. The owner decided A1, A2 and A8 on 2026-11-23;
A3–A7 follow from the spec and the review, and are stated so the review can check them.

- **A1 Argument names (owner: yes).** `recall` and `retain` take `run_id`, `agent_id` and `task_id`, the names of the
  environment variables (`MEMKERNEL_RUN_ID`, `MEMKERNEL_AGENT_ID`, `MEMKERNEL_TASK_ID`, FR-002). H2 reuses
  `agent_id` and `task_id` for scope, so FR-001's "the caller's `agent` and `task`" means these two arguments: a
  caller passes its ids once, and from H2 they also widen `recall` to that agent's or task's records. In H1 they are
  only logged.
- **A2 What a retained record keeps (owner: yes).** `run_id` only, as FR-002 says (`agent_id` and `task_id` reach the log,
  not the record; H2's `scope` carries an agent or task where it matters). A new metadata key that loads as `""` from
  older stores. Set when a record is created, like `source_hash`: a retain that matches an existing record keeps that
  record's `run_id`, so it names the run that created the memory.
- **A3 Receipt fields.** Each recall-log record, MCP `recall` and hook block alike, adds `run_id`, `agent_id`,
  `task_id`; `memories`, one entry per returned memory in `ref_ids` order (`ref_id`, `content_hash`, `source`,
  `source_hash` where it has one, `state`: `live` or `flagged`); `returned_chars` (the length of the MCP
  response the agent receives, or the block's length); and, for MCP `recall`, `latency_ms` and `excluded` (`superseded`, withdrawn included, `flagged`,
  `expired`). `ref_ids` stays as it is, so the count and older readers work unchanged.
- **A4 What `excluded` counts.** Candidates the search returned in its last window and the live filter dropped, by
  reason: not the whole store. `recall(order="newest")` selects by metadata and reports `excluded` as absent, not
  zero. H2 adds `out_of_scope`.
- **A5 One size limit.** Receipts make records larger. A record over `recall_log_max_bytes` drops, in order: query
  text, then the per-memory details (trailing `memories` entries, marked `memories_truncated`), then trailing
  `ref_ids` (marked `ref_ids_truncated`, as now). Each cut marks the record `truncated`. `ref_ids` go last, so the
  count keeps the evidence it relies on.
- **A6 The count (FR-006).** When attributed log records carry `run_id` or `agent_id`, the report adds `by_run` and
  `by_agent`: the same outcome counts per id. Without ids the report is unchanged.
- **A7 Ids are caller text, capped.** `run_id`, `agent_id` and `task_id` are at most 128 characters. A longer call
  argument is refused with an error naming the limit; a longer environment value is ignored, with one warning per
  process. So a harness cannot bloat the log or the records with them.
- **A8 Hashing scheme in the receipt (owner: yes).** Each `memories` entry records the scheme that produced its
  `content_hash`, one short field (`content_hash_scheme`, today `sha256-raw`: SHA-256 of the UTF-8 content). If #59's
  S4 (#153) changes the hashing, H3 can then tell "hashed differently" from "content changed", and S4 need not be settled
  before H3. Order after H1 (the owner, 2026-11-23): H2, H3, then S4 (#153) and #90's build in either order.

Unchanged: the MCP tool set and the `recall` response (a JSON list); `MemoryService.recall` returns the same list
(the receipt comes back through an optional argument); the log stays off unless `MEMKERNEL_RECALL_LOG` is set.

## Amendment H2: scope and abstention (draft, 2026-11-23)

The H2 build (D5: FR-001, FR-005, SC-1, SC-4, SC-6) as it will be built. H1's ids are the caller: `agent_id` and
`task_id` (A1), from the call or the process. Decisions B1–B5 await the owner; B6–B11 follow from the spec and are
stated so the review can check them.

- **B1 How `retain` names a scope (owner).** `retain(scope=…)` takes `project` (the default), `agent` or `task`,
  meaning the caller's own `agent_id` or `task_id`; the record stores `agent:<id>` or `task:<id>`. A call without
  that id is refused. So a caller cannot write into another agent's scope by a typo, and the stored form is the
  spec's. (The alternative, a free `agent:<id>` string, lets one agent write a note only another agent can see.)
- **B2 An out-of-scope record by id (owner).** `get`, `ask`, `forget`, `promote` and a `supersedes=` target treat a
  record the caller cannot see as not found, the same answer as a missing one: `get` and `ask` return not found,
  `forget` returns `deleted: false`, and a `supersedes=` target is ignored, as a missing one is today. Scope is a
  convention (FR-001), so this hides nothing from a hostile client; it keeps every path giving one answer. The cost:
  an agent that names another agent's record by mistake gets "not found", not a scope error.
- **B3 Wiki export (owner).** `wiki_export` drafts pages from `project` records only, whoever calls it: a wiki is
  shared knowledge, and a private note becomes shared only by promoting it with `scope="project"` first.
- **B4 Hook checkpoints (owner; recommended: scoped to the agent).** A checkpoint the hooks save (session end,
  compaction) is `agent:<MEMKERNEL_AGENT_ID>` when that variable is set, and `project` otherwise. With two agents on
  one project, each session start and compaction recovery then shows that agent's own newest checkpoint, not the
  other agent's current task (scenario 1). A single-agent user without the variable sees no change; one with it set
  keeps seeing their own checkpoints, since every session of that agent carries the same id. Tools that share one
  store (#107) must then set the same `MEMKERNEL_AGENT_ID`, or none: if Claude Code sets it and Codex does not, a
  session started in one is not continued in the other, because Codex cannot see Claude Code's agent checkpoints.
  The README's "One store across tools" section and the Codex and Cursor templates say so. (The alternative keeps
  every hook checkpoint `project`, as today: then agent A's session start can show agent B's checkpoint, a limit the
  README would have to state.)
- **B5 Filtering in Python, not in the store (owner).** Scope is applied after the store returns candidates, by one
  predicate, on every path. A store `where` filter cannot match the records older stores wrote without the key
  (SC-4), and the BM25 index has no metadata. Cost: recall's window widens past out-of-scope candidates, as it
  already does past superseded ones: it keeps doubling until it has `top_k` visible results or the store runs out,
  however many of the top candidates are another agent's. One predicate decides visibility everywhere, and it reads
  a record without the key as `project`.
- **B6 Storage.** Metadata key `scope`, written only when not `project`; absent loads as `project` (SC-4). An explicit
  `scope="project"` is stored the same way as the default: the two mean the same. Older records are not migrated:
  dedup, like every other path, reads a missing key as `project`, so a pre-H2 record and a new `project` record with
  the same text are one record.
- **B7 Who the caller is on each path.** MCP: `recall`, `retain`, `get`, `ask`, `forget`, `promote` and
  `consolidate` take `agent_id` and `task_id` (H1's two on `recall`/`retain`, new on the others), each defaulting
  to `MEMKERNEL_AGENT_ID`/`MEMKERNEL_TASK_ID`. Hook blocks use the process's. The Python API takes them on the same
  `MemoryService` methods, defaulting to the settings. A caller with neither sees `project` records only (FR-001).
  The admin API (`src/memkernel/api/`) is the operator's and sees every record, the full health report
  (`/health/store`, with `ref_id`s) included.
- **B8 Every read path (SC-1).** `recall` (both orders), `get`, `list_memories`, `ask`, `consolidate`'s promotion
  candidates (it lists them; `promote` writes, per B9), the hook blocks (checkpoint, long-term context, needs-review list, candidates), and `wiki_export`
  (B3). Store maintenance stays store-wide: purge, revalidation, and the health summary, which reaches callers
  (`consolidate`'s `health`, the session-start block) as counts only, never as records.
- **B9 Writes.** Dedup is per scope: identical text in two scopes is two records, so a private note never merges into
  a project one; the two copies are not linked, and the private one reaches the wiki only by `promote` with
  `scope="project"` (B3). `promote` keeps the source's scope; `scope="project"` publishes, never by default (FR-001).
  `supersedes=`, `forget` and `promote` need a target the caller can see (B2). Records memkernel writes itself, the
  wiki import's pages and capture's records, are `project`; `withdraw` is the wiki import's own path on those records,
  not an MCP tool, and takes no caller.
- **B10 Exclusion counts.** `excluded` adds `out_of_scope` and `capped` (the limit of 3 captured records per session,
  left out of H1's counts). Each dropped candidate counts once, under the first reason that applies, in this order:
  `out_of_scope`, `superseded`, `flagged`, `expired`, `capped`. An out-of-scope candidate is never in the receipt's
  `memories` or `returned_chars`.
- **B11 Abstention (FR-005, SC-6).** An empty `recall` puts `empty_reason` in its receipt: `no_match` (the last
  window had no candidates), `out_of_scope` (every candidate counted as `out_of_scope`), or `excluded` (any other
  mix). The MCP response stays a JSON list.

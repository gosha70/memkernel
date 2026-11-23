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

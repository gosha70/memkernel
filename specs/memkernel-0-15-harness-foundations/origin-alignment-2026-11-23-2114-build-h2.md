# Origin alignment check — memkernel-0-15-harness-foundations, the H2 build

Origin: #119 Part 1 (Task-Scoped Knowledge), the reviews the owner passed on, and the owner's decisions: D1–D6
(2026-11-19), amendment H1 (2026-11-23), amendment H2 with B1, B2, B3, B5 confirmed and B4 revised by the owner
(2026-11-23, PR #155).

Origin claim: as in plan.md. Part 1: task-, feature- and agent-aware retrieval; controlled sharing of approved project
knowledge; isolation of private or temporary agent memory; exclusion of irrelevant or superseded information; explicit
abstention; compatibility with existing consumers. Success scenario: two agents share approved decisions while keeping
private task notes separate.

Working claim:
> Built as amendment H2 says: a `scope` on records (`project`, `agent:<id>`, `task:<id>`; absent loads as `project`),
> applied by one predicate on every read path (`recall` both orders, `get`, `list_memories`, `ask`, `consolidate`'s
> candidates, the hook blocks, `wiki_export` project-only) and on writes (dedup per scope, `promote` keeps scope,
> private records supersede only their own scope, invisible targets not found); checkpoints in the caller's effective
> scope (task, else agent, else project) with recovery from that scope only; store maintenance and the admin API
> store-wide; `out_of_scope` and `capped` in `excluded`; `empty_reason` in the receipt; the MCP response unchanged.

Mismatches:
  - none. "Feature-aware" is served by the task id, as D1 decided (a task id may name a feature or ticket). Callers
    without ids and stores written before H2 see no change; anyone setting `MEMKERNEL_AGENT_ID` or
    `MEMKERNEL_TASK_ID` (new in H1, unreleased) gets private checkpoints, as B4 decided; the README and CHANGELOG say
    so.

Verdict: aligned
Confidence: high

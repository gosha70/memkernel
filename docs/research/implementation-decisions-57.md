# Research: preserving and retrieving implementation decisions (#57)

Status: research note, 2026-11-10. Not a spec, and not an approval for any new API or schema. It answers #57's
research questions from two sources: what memkernel 0.9 already does, read from the code, and outside prior art
from a multi-agent web search. That search used 5 search angles and 20 sources fetched. 25 claims were checked by
three independent votes each: 22 were confirmed and 3 refuted.

## Summary

- **memkernel can already store a decision record.** `retain(type="decision")` takes free text, `source`, `tags`,
  `importance` and `supersedes`. `recall` returns only live memories (not superseded, not flagged for review). So
  a structured decision record is a content convention, with no new record type, as #57 asks.
- **Prior art for the record:** MADR 4.0.0 gives the fields (context, options, chosen option and why). A
  Y-statement gives a one-line summary that indexes well. Neither has a machine-checkable revisit condition or
  provenance, so those go in the convention.
- **Prior art for staleness:** two working patterns.
  - GitHub Copilot memory checks a memory's code citations against the current branch just before using it.
  - Zep/Graphiti keeps superseded facts with a closed validity window.

  memkernel has supersession, and has file-hash revalidation for `code` memories only.
- **The main gap found:** a `decision` that cites a file is never flagged when that file changes. Revalidation
  covers `type == code` only (`core/services.py`, `revalidate`). This is #57's "stale decision" risk, and
  conventions cannot close it on their own.
- **No source shows that retrieval at the decision point actually prevents re-implementation.** The closest
  evidence suggests prompt guidance alone lowers duplication at first but does not slow its growth.
- **Recommendation:** docs and skill first. Measure on a small replay corpus. Propose one small runtime change
  (revalidating decisions that cite files) only if the corpus shows stale retrievals.

## 1. What memkernel offers today (repository evidence, `main` at 0.9.0)

| Need in #57 | Today | Evidence |
|---|---|---|
| A place for decisions | `MemoryType.DECISION`, long-term | `src/memkernel/core/models.py` |
| Record fields | free-text `content`, plus `source`, `tags`, `importance`, `supersedes` | `retain` in `src/memkernel/mcp/tools/memory.py` |
| Retrieval | hybrid BM25 and embedding `recall(query, type, tier, session_id, top_k)` | `recall` in `mcp/tools/memory.py` |
| Hide outdated decisions | `recall` returns live memories only; a successor is retained with `supersedes=<ref_id>` | `core/services.py` (liveness) |
| Staleness against code | file-hash revalidation, but **`code` memories only** | `core/services.py`, `revalidate` lists `{"type": "code"}` |
| Filter by tag or path | **none**: tags are stored but `recall` cannot filter on them | `recall` signature |
| Duplicates | exact content-hash idempotency only; no near-duplicate merge | `memory/dedup.py` |
| Curated corrections | a wiki page's `corrects: <ref_id>` supersedes runtime memories on `wiki_import` | README, "Corrections" |
| Agent guidance | code-copilot-team's `memkernel-memory` skill: "recall prior decisions instead of guessing", "one focused memory per decision"; no record structure | `code-copilot-team/shared/skills/memkernel-memory/SKILL.md` |

## 2. Findings by research question

### Q1. Can current types express a useful decision record?

Yes, as a content convention. The best-fitting template is **MADR 4.0.0**:
- required: Context and Problem Statement, Considered Options, Decision Outcome ("Chosen option: X, because Y");
- optional: Decision Drivers, Consequences, Confirmation, Pros and Cons of the Options, More Information.

The reasons for rejecting an option live only in the optional Pros and Cons section. MADR has no revisit or expiry
field, records supersession only as a status ("superseded by ADR-NNNN"), and its Confirmation section is free text.
[MADR](https://adr.github.io/madr), [template 4.0.0](https://raw.githubusercontent.com/adr/madr/4.0.0/template/adr-template.md)

A **Y-statement** puts a decision in one sentence: "In the context of …, facing …, we decided for … and neglected …,
to achieve …, accepting …, because …". It has no provenance, scope or revisit slot. Nygard ADRs have no section
for alternatives. [ADR templates](https://adr.github.io/adr-templates)

**GitHub Copilot memory** stores `subject`, `fact`, `citations` (file:line) and `reason`. That is the minimum
production design: a claim, where in the code it is grounded, and why it was kept.
[GitHub blog](https://github.blog/ai-and-ml/github-copilot/building-an-agentic-memory-system-for-github-copilot/)

Proposed convention (content only, no schema change):

```
decision: <Y-statement, one line: context, chosen option, rejected options, because>
requirement: <what was needed; scope where this applies>
chosen: <existing helper / native capability / dependency, with path or symbol>
rejected: <option>: <reason or evidence>; <option>: <reason>
evidence: <repo>@<commit> <path>[:<symbol>]; tests: <test id or result>
revisit-when: <condition, e.g. "Python ≥ 3.14 is the floor" or "requirement X changes">
```

- Put the first cited path in `source`, so a future runtime check has something to read.
- Add tags for the capability (for example `capability:retry`) and the path area.
- When a decision changes, retain its replacement with `supersedes=<ref_id>`.

### Q2. How should a harness query before generating code, without bloat?

- **Claude Code** keeps a small index loaded at start (MEMORY.md, first 200 lines or 25 KB) and reads topic files
  only when needed. [Claude Code memory](https://code.claude.com/docs/en/memory.md)
- **Copilot** does not send every memory with a prompt. It ranks with upvotes and downvotes, and a memory expires
  after 90 days by default (7–180 configurable) unless it is validated again. [Copilot memory docs](https://docs.github.com/en/copilot/concepts/agents/copilot-memory)
- **projectmem** (a 2026 preprint, abstract only) runs a file-scoped check before an edit. It returns recorded
  failures, open issues and churn for the target file, which is retrieval at the decision point, scoped by path.
  Its authors say they have not shown that it prevents repeated failures.
  [arXiv 2606.12329](https://arxiv.org/abs/2606.12329)
- **LongMemEval** found that indexing by extracted facts, not raw text, raised recall@k by 9.4% and QA accuracy
  by 5.4%. That result is on chat histories, not code. [arXiv 2410.10813](https://arxiv.org/abs/2410.10813)

For memkernel: the skill tells the agent to call `recall("<capability> <path or symbol>", type="decision",
top_k=3)` before adding a helper, dependency or module. The Y-statement first line is what gets indexed and shown
in the preview; the agent calls `get(ref_id)` only for a hit it will act on.

### Q3. Provenance, and recognising stale or superseded decisions

Three patterns:
1. **Check at read time** (Copilot): before using a memory, the agent checks its citations against the current
   branch. If they no longer hold, it stores a correction; if they hold, it refreshes the memory. This is prompted,
   not enforced, and Copilot's docs say it will not catch everything.
2. **Bi-temporal validity** (Zep/Graphiti): each fact has ingestion and validity timestamps, and an invalidated
   fact keeps its history with a closed validity window. [arXiv 2501.13956](https://arxiv.org/abs/2501.13956)
3. **Audit by convention** (Claude Code): near the size cap, the agent is reminded to drop stale entries, and
   `/doctor` can flag references to files that no longer exist.

memkernel already has (2) in a simpler form: `supersedes` keeps the old record and hides it from `recall`. It has
an automatic version of (1) for `code` memories, through file-hash revalidation. **The gap is decisions:** a
decision citing `src/x.py` stays live after `src/x.py` is rewritten or deleted.

### Q4. Conflicting decisions

No surveyed product has a defined policy. Claude Code's docs say that with contradictory instructions Claude "may
pick one arbitrarily", and leave resolution to human review. Copilot has the agent store a corrected memory. A
claim that Graphiti resolves conflicts automatically by last-writer-wins was refuted, 0 votes to 3.

Proposed rule for the skill, under the harness's existing clarification protocol: when `recall` returns two live
decisions with different `chosen` for overlapping scope, show both with their `evidence` and dates, and ask the
user before acting. Never merge them silently.

### Q5. Evaluating retrieval on a replayable corpus

- No code-reuse or decision-retrieval benchmark survived verification. A claim that LongMemEval's knowledge-update
  and abstention categories map onto stale-decision and false-reuse metrics was refuted, 0 votes to 3.
- **SlopCodeBench** (a 2026 preprint) is the closest evidence. Agents extending their own code over 3–8
  checkpoints showed rising structural erosion in 77% of runs and 96% growth in duplicated lines. Quality guidance
  in the prompt lowered initial erosion by up to about a third, but did not change how fast it grew, and cost
  about 12% more per checkpoint. It tests one agent on changing specs, not retrieval across sessions, so it is only
  an analogy here. [arXiv 2603.24755](https://arxiv.org/abs/2603.24755)

memkernel needs its own small corpus, reusing the lifecycle suite's runner and oracle pattern (#17), with labelled
cases:
- **reuse:** an existing helper fits, so the correct answer is to reuse it;
- **native vs dependency:** a platform capability was chosen over a library;
- **rejected for safety:** a recorded rejection must stop the rejected approach;
- **stale:** the decision's cited file changed, so the decision must not be applied as is;
- **false-reuse trap:** a similar-looking decision for a different requirement;
- **conflict:** two live decisions disagree, so the agent must ask.

Metrics: reuse discovered, correct choice, stale retrieved and applied, false reuse, extra tokens, and latency per
decision point.

### Q6. Where governance lives

The surveyed systems split the work the way #57 proposes:
- fast runtime memory, validated just in time (Copilot), or by convention (Claude Code);
- curated reference material reviewed by humans.

memkernel already has the bridge: an approved wiki page can supersede runtime memories with `corrects:`. A decision
worth trusting widely is promoted to a wiki-studio page (a curated pattern). The runtime record keeps working
without wiki-studio installed. This does not touch #48's governed-import contract.

## 3. Recommendation

1. **Docs and skill (now, no memkernel change):**
   - add the decision convention above to code-copilot-team's `memkernel-memory` skill and memkernel's
     `templates/claude-memory-instructions.md`;
   - add a "recall before building" step: query by capability and path, `type="decision"`, small `top_k`;
   - add a read-time check: confirm `evidence` paths still exist and still match before reusing;
   - add the conflict rule (show both and ask).
2. **Measure (read-only):** build the replay corpus in Q5 with real CCT examples. Run it against unchanged
   memkernel, and publish the false positives and misses.
3. **Only if the corpus shows stale decisions being applied: one small runtime change**, with its own spec:
   - extend revalidation to `decision` memories whose `source` names a file in the project, flagging them
     `needs_review` when the file is missing or its hash changed since retain (memkernel would record a hash at
     retain);
   - decisions retained before a source-hash key exists are flagged only when the cited file is missing;
   - this reuses the existing `code` mechanism and settings, adds no record type, and keeps `recall`'s default of
     hiding flagged memories.

   A tag or path filter on `recall` is a second candidate, justified only if the corpus shows irrelevant hits that
   ranking does not fix.

Not recommended, per #57's scope: a new record type, automatic merging or deletion, or deciding automatically that
an old decision fits a new requirement.

## Caveats

- Coverage is uneven: Cursor, Devin, Cline, Windsurf, Mem0 and Letta produced no verified claims, so Q2 rests on
  Copilot, Claude Code and projectmem.
- projectmem and SlopCodeBench are single-source 2026 preprints. projectmem was read from its abstract only, and
  one of its fact-check votes ran while the session's safety classifier was unavailable.
- Product details (Copilot's expiry ranges, Claude Code's 200-line/25 KB cap and `/doctor` audit) change over time;
  they were checked on 2026-11-10.
- The recommendations are a synthesis of these findings, not results from any one source.

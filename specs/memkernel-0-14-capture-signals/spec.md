# Spec: capture signals with real yield, owner answers and session outcomes (#59 Phase 2, S3)

Status: approved by the owner, 2026-11-18 ("#142: go with the recommendations"): D1–D7 as listed below. Drafted
overnight on the owner's instruction to open a PR per issue; nothing here is built yet. S3's issue is #147 (filed 2026-11-18,
#59 D5: one issue per slice); S4 is noted on #59.

## Checked facts (`main` at `4ef72c2`)

- **S2 is in place** (#137): the spool keeps ended sessions until capture commits them; `capture.run()` runs one
  extractor (failed-then-fixed) behind the capture lock, a time budget and record caps; records are keyed by
  (session, call, extractor) with the version as a tag, redacted (FR-006, R16), and never promotion candidates.
- **The reader returns tool steps only.** `ClaudeCodeTranscriptReader` reads `tool_use` and `tool_result` parts; it
  does not read the entry-level `toolUseResult` field, where Claude Code keeps an `AskUserQuestion` call's structured
  `questions` (header, question, options with label and description) and `answers` (question → chosen label, or
  the owner's own text when they chose "Other").
- **Yield on the local transcripts** (77 files, 78 sessions, the owner's projects, measured 2026-11-18), against
  failed-then-fixed's 1 pair in 289 failures:

  | Candidate | Yield | Sessions |
  |---|---|---|
  | Owner answers (`AskUserQuestion`, structured) | 222 answers: 149 an offered option, 73 the owner's own text | 17 |
  | PRs opened (`gh pr create` passed, a `/pull/` URL in its output) | 252 | 13 |
  | Issues filed (`gh issue create` passed, an `/issues/` URL) | 61 | 14 |
  | PRs merged (`gh pr merge` passed) | 58 | 10 |
  | Files edited (`Edit`/`Write` with a result and no error) | 3,171 steps | 58 |
  | Commits (`git commit` passed) | 1,045 | — |

- **Owner answers per session** (the same 17 sessions): 65, 37, 23, 20, 10, 10, 8, 7, 7, 7, 6, 6, 5, 4, 4, 2, 1.
  What a per-session cap would keep:

  | Cap | Answers kept | Sessions over the cap |
  |---|---|---|
  | 5 | 76 of 222 (34%) | 12 |
  | 15 | 137 (62%) | 4 |
  | 20 | 157 (71%) | 3 |
  | 30 | 180 (81%) | 2 |

- **How captured records rank today:** never in the startup context (it lists long-term memories only), never
  promotion candidates (S2 D5). In `recall`, relevance weighs 1.0, importance 0.3 (an observation's default
  importance is 0.3, a decision's 0.9) and recency 0.3 (half-life 7 days), so a decision outranks a captured answer
  when relevance ties. Nothing limits how many records from one session fill a recall result.
- **#59's prompt-injection rules** (its Phase 2 text): "free text only from owner turns and structured fields; tool
  and web text quoted, never re-injected verbatim; nothing of tool or web origin promoted automatically."

## User Scenarios

1. In a session the agent asks the owner whether to keep the old API, and the owner picks "Deprecate it, remove in
   1.0". A later session, in any tool sharing the store, recalls that answer when the API comes up again.
2. A session opens a PR and files an issue. The next session's recall of "what did I do on the capture work" returns
   one record naming them and the files the session changed.

## Requirements

- **FR-001 Reader: structured answers.** A `ToolStep` for an `AskUserQuestion` call carries its questions (header,
  question, the options' labels and descriptions) and its answers, from the entry's `toolUseResult`. Other steps are
  unchanged.
- **FR-002 Extractor: owner answers (D1, D2).** One record per answered question: the question's header and text,
  the chosen option's label and description (or the owner's own text, per D2), and the other offered labels. A
  multi-select answer (several options for one question) is one record listing every chosen label with its
  description, in the order offered. Type per D3. Key: (session, the call's `tool_use_id`, extractor, the question's
  index). Redacted (FR-006).
- **FR-003 Extractor: session outcome (D4).** One record per session that opened or merged a PR, filed an issue or
  edited files: the PR and issue URLs, and the edited files (at most `OUTCOME_FILES`, then a count). The URLs are
  found by shape: a GitHub `https://github.com/<owner>/<repo>/pull/<n>` or `/issues/<n>` URL in the result of a call
  that **creates** a PR or an issue, or of one that **merges** a PR. Which calls count:
  - **creates:** a `gh pr create` or `gh issue create` run, or an MCP tool whose name contains `create`, or whose
    input has `method: create` (GitHub's MCP server files an issue with `issue_write`, method `create`);
  - **merges:** a `gh pr merge` run, or an MCP tool whose name contains `merge`, or whose input has
    `method: merge`;
  - **anything else is ignored,** however many URLs its result holds: read and list calls (`pull_request_read`,
    `list_pull_requests`, `issue_read`, `gh pr view`) return `html_url`s too, and a session that only looked at PRs
    must record no outcome.

  Matching by URL shape covers servers whose tool names differ; the create or merge test keeps reads out. A merge's result may carry no URL, so a merged PR's URL is built
  from the call's input (owner, repo and PR number; for `gh pr merge`, the number or URL argument and the session's
  repository). Sessions that work through the MCP tools, as cloud sessions do, would otherwise record no outcome.
  The local transcripts hold no GitHub MCP calls, so that path's yield is unmeasured; the build cuts a fixture from
  a real session that uses them, which shows the result shapes that occur. Type `episode`, short-term. Key: (session, extractor). Commits are left out: git already holds them, at a
  yield (1,045) that would crowd the store.
- **FR-004 Caps (D5).** The per-session cap applies per extractor, so a session's answers cannot push out its
  outcome record. Owner answers keep a session's **last** 30 answers in transcript order, since later answers often
  revise earlier ones; failed-then-fixed and session outcome keep the first N (S2's R4). An ended session's
  transcript does not change, so "the last 30" is the same set on every retry. The per-run cap and the time budget
  stay as in S2: the run cap stops capture from starting another session, and a session already started is finished
  under its own caps (one startup can embed about 50 records, well inside the 3-second soft budget).
- **FR-005 Promotion (D6).** Captured records stay out of the promotion candidates (S2 D5), except owner answers:
  at most `ANSWER_CANDIDATES` (2) of them appear among the candidates, ranked like any candidate, so they reach the
  agent without a search and cannot push out the agent's own memories.
- **FR-006 The #120 count and the report.** The startup report's capture line counts records per extractor. The
  count is unchanged (neither extractor stores an error).
- **FR-007 Docs.** README "Capture": the two extractors, their yields, and what each stores; CHANGELOG.
- **FR-008 A recall limit per origin session (D7).** One `recall` result holds at most 3 captured records from any
  one origin session (`origin-session:` tag); further ones are skipped and the window widens, as recall already does
  for filtered results. Records the agent stored itself are not limited.

**Constants** (in `capture.py`, beside S2's):

| Constant | Value | Why |
|---|---|---|
| `ANSWER_SESSION_MAX` | 30, the last in transcript order | D5, from the per-session table |
| `OUTCOME_FILES` | 10 | Names the files a session mostly worked on; the rest is a count ("and 23 more"). |
| `ANSWER_CANDIDATES` | 2 | D6: owner answers among the promotion candidates, so they cannot crowd out the agent's own. |

## Constraints / What NOT to Build

- No model-written text (#59 D4); no transcript excerpts beyond the owner's own answer text (#59 D3, its free-text
  rule).
- No supersede suggestions at retain and no canonical hashing in this slice: they are store features, not
  extractors; proposed as their own slice (S4).
- No commits extractor (FR-003); no "owner turns" extractor for free-form chat messages (unstructured: no
  question, no options, so no reliable signal to key or quote).
- No readers for other tools (#107, later work).

## Key Entities

- **Owner answer:** a captured record of one answered `AskUserQuestion` question.
- **Session outcome:** a captured record of one session's PRs, issues and edited files.

## Success Criteria

- **SC-1** A fixture transcript with an `AskUserQuestion` call (two questions, one an offered option, one the
  owner's own text) yields two owner-answer records with the FR-002 content; a cut from a real transcript.
- **SC-2** A fixture session that opens a PR, files an issue and edits three files yields one outcome record, from
  `gh` output and, in a second fixture, from GitHub MCP tool results (an issue filed with `issue_write`, a merge
  whose result carries no URL); a session with none of these yields none, and so does a session whose only GitHub
  calls are reads (`pull_request_read`, `list_pull_requests`, `issue_read`) returning PR and issue URLs. A
  multi-select answer yields one record listing every chosen label.
- **SC-3** Re-capturing a session stores nothing twice (the S2 key rules), and the caps hold per extractor; a session
  with 35 answers stores its last 30, the same 30 on a retry.
- **SC-4** Fast suite, ruff, mypy strict, coverage ≥ 80%.
- **SC-5** A recall whose top matches are 6 captured answers from one session returns 3 of them and the next-best
  records from elsewhere (FR-008).

## Decisions (the owner's, 2026-11-18)

- **D1 First S3 extractors: owner answers and session outcomes.** They have the yield (222 answers in 17 sessions;
  outcomes in 58 of 78 sessions) and keep to structured fields.
- **D2 The owner's own text in an answer ("Other").** Include it: #59's rules allow free text from owner turns, and
  73 of 222 answers are the owner's own words, often the actual decision. Included, redacted.
- **D3 Record type for an owner answer: `episode`** (short-term, kept 30 days, `episode_ttl_days`). Not `decision`,
  which is long-term by type and would enter long-term memory without the agent choosing; not `observation`, which
  expires after 7 days (`observation_ttl_days`), so an answer nobody promoted within a week would be lost and the
  first user scenario would fail.
- **D4 Session outcome contents:** PR and issue URLs, matched by URL shape in `gh` output and GitHub MCP results
  (a merge's URL built from its input), counted only for create and merge calls, plus edited files; no commits.
- **D5 Caps:** owner answers 30 per session, keeping the **last** 30; failed-then-fixed and session outcome as in S2
  (5 per session, the first N); the run cap of 20 shared. The owner's choice of 30 and "keep the last", from the
  per-session table (2026-11-18); a cap of 5 would keep 34% of the answers.
- **D6 Promotion: at most 2 owner answers among the promotion candidates;** every other captured record stays out
  (S2 D5). With D3's 30 days, an answer reaches the agent at startup without a search, while the agent's own
  memories keep the other places.
- **D7 A recall limit per origin session:** at most 3 captured records per origin session in one recall result, so
  one heavy session cannot fill it (FR-008).

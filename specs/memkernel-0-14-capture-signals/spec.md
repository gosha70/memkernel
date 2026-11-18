# Spec: capture signals with real yield, owner answers and session outcomes (#59 Phase 2, S3)

Status: draft, 2026-11-18. Written overnight on the owner's instruction to open a PR per issue; D1–D6 are
**proposed, for the owner's decision**, and nothing here is built yet. S3 has no issue of its own (#59 D5: one
issue per slice); filing it is the owner's call.

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
  the chosen option's label and description (or the owner's own text, per D2), and the other offered labels. Type
  per D3. Key: (session, the call's `tool_use_id`, extractor, the question's index). Redacted (FR-006).
- **FR-003 Extractor: session outcome (D4).** One record per session that opened or merged a PR, filed an issue or
  edited files: the PR and issue URLs from `gh`'s output, and the edited files (at most `OUTCOME_FILES`, then a
  count). Type `episode`, short-term. Key: (session, extractor). Commits are left out: git already holds them, at a
  yield (1,045) that would crowd the store.
- **FR-004 Caps (D5).** The per-session cap applies per extractor, so a session's answers cannot push out its
  outcome record; the per-run cap and the time budget stay as in S2.
- **FR-005 Promotion (D6).** As S2: captured records are never promotion candidates, unless D6 says otherwise for
  owner answers.
- **FR-006 The #120 count and the report.** The startup report's capture line counts records per extractor. The
  count is unchanged (neither extractor stores an error).
- **FR-007 Docs.** README "Capture": the two extractors, their yields, and what each stores; CHANGELOG.

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
- **SC-2** A fixture session that opens a PR, files an issue and edits three files yields one outcome record; a
  session with none of these yields none.
- **SC-3** Re-capturing a session stores nothing twice (the S2 key rules), and the caps hold per extractor.
- **SC-4** Fast suite, ruff, mypy strict, coverage ≥ 80%.

## Decisions (proposed, for the owner)

- **D1 First S3 extractors: owner answers and session outcomes.** They have the yield (222 answers in 17 sessions;
  outcomes in 58 of 78 sessions) and keep to structured fields. Recommended.
- **D2 The owner's own text in an answer ("Other").** Include it: #59's rules allow free text from owner turns, and
  73 of 222 answers are the owner's own words, often the actual decision. Alternative: offered options only.
  Recommended: include, redacted.
- **D3 Record type for an owner answer:** `decision`, short-term? memkernel's `decision` is long-term (tier by
  type), so a captured answer as `decision` would enter long-term memory without the agent choosing. Recommended:
  `observation` (short-term), with the owner's answer quoted, so the agent promotes it as a decision when it holds.
- **D4 Session outcome contents:** PR and issue URLs plus edited files, no commits. Recommended.
- **D5 Caps:** 5 per extractor per session, the run cap of 20 shared. Recommended.
- **D6 Promotion:** owner answers stay out of the promotion candidates like every captured record (S2 D5).
  Alternative: allow owner answers as candidates, since they are the owner's decisions. Recommended: keep them out
  for now; the agent's own promote path is unchanged.

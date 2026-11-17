# Spec: capture core, failed-then-fixed commands from ended sessions' transcripts (#134)

Status: draft, 2026-11-16. Decisions D1–D6 are the owner's (2026-11-16; D6's values proposed by this spec and
approved). D7, the command-matching rule, is open.

## Checked facts (`main` at `7f26012`, memkernel 0.9.0)

- **The spool** (`session_spool.py`): `drain()` removes every ended session, other than the current one, and
  returns only the windows with no checkpoint (`DrainResult.unsaved`); the "previous sessions" block lists them,
  once, because they are removed. `SessionWindow` has no `transcript_path`, though the SessionEnd hook writes one on
  the `ended` line (`templates/hooks/session-end.py`). Unended sessions older than `SPOOL_UNENDED_MAX_AGE` (7 days)
  are removed and counted. A line whose event is not `started` or `ended` is removed as malformed.
- **The drain runs only at normal startup** (`on_session_start`, `source == "startup"`), before `consolidate()`.
- **The SessionEnd hook has a 1.5-second budget** and imports only the settings; it holds the spool lock while it
  appends.
- **Claude Code's transcript** (JSONL, one entry per line; checked on a local transcript): each entry has `uuid`,
  `sessionId`, `timestamp` and `isSidechain`. A tool result is a `tool_result` part of a user message, with
  `tool_use_id`, `content` and `is_error`; a denied tool call's entry also carries `toolDenialKind`. A `tool_use`
  part has `id`, `name` and `input` (`command` for `Bash`, `file_path` for `Edit`/`Write`).
- **`is_error` on real transcripts** (checked 2026-11-16 on the 65 local Claude Code transcripts of the owner's
  projects):
  - a `Bash` command that exits non-zero has `is_error: true`, and its content starts with `Exit code <n>`;
  - a command that prints an error but whose last exit status is 0 has `is_error: false`: for example a heredoc
    `python3` script that raised `AssertionError`, followed by commands that succeeded (in `fixtures/not-captured.jsonl`);
  - `is_error: true` also marks calls that never ran: permission denials (with `toolDenialKind`) and harness blocks,
    whose content starts with `<tool_use_error>`;
  - some results have no `is_error` key (an `Edit` result, for example); absent means false;
  - entries without a message (`last-prompt`, `api-request` and others) are interleaved with the conversation.
- **Yield of the matching rule** (same transcripts): 289 `Bash` results with a non-zero exit, main thread only. A
  later passing run of the **exact** command (whitespace collapsed) follows 2 of them; of the command **with a
  trailing pipe or `2>&1` removed**, 12; of the command's **first two words** (after `cd … &&` and `VAR=…`
  prefixes), 193, but two words such as `poetry run` or `git push` do not identify a command.
- **The #120 reader** (`eval/repeat-mistakes/transcripts.py`) reads a folder of transcripts by `sessionId`: each
  session's window, its `Bash` outputs and its `recall` calls. The count (`count.py`) treats a memory's
  backtick-quoted span containing one of `ERROR_WORDS` as a stored error.
- **Promotion candidates** come from `MemoryService.consolidate()`: live, non-long-term, non-checkpoint records that
  are not a promoted memory's source, ranked by importance × (1 + access count). The MCP `consolidate` tool and the
  startup block both use it.
- **`retain()`** is idempotent on identical content and type (it returns the existing `ref_id`), takes `session_id`,
  `source` and `tags`, and stores tags as one comma-separated string.
- **memkernel has no redaction code** in `src/`.

## User Scenarios

1. With capture on, a session runs `pytest`, it fails, the agent edits a file, `pytest` passes. At the next normal
   startup, memkernel stores one short-term observation saying which command failed, with which error, and what
   came between the failure and the passing run.
2. A later session repeats the same failure; the #120 count shows the error was captured before, and whether a
   recall or hook block showed it first.
3. With capture off (the default), memkernel reads no transcript and stores nothing new.

## Requirements

- **FR-001 Spool: every ended window.** `SessionWindow` gains `transcript_path` (empty when the line has none).
  `DrainResult` gains `ended`: every ended session's window, the unsaved ones included. The unsaved report is
  unchanged: each unsaved window is reported once.
  - **Capture off:** `drain()` behaves as today, removing every ended session.
  - **Capture on:** `drain()` keeps ended sessions in the spool and marks the unsaved ones with a `reported` line.
    A session with a `reported` line is in `ended` but never again in `unsaved`. A new `session_spool.commit(settings, session_ids)` removes sessions under the
    spool lock. A new `capture_missed` line is appended for each failed attempt to read a session's transcript; a session's
    miss count is its number of `capture_missed` lines. Ended
    sessions still in the spool `SPOOL_UNENDED_MAX_AGE` after their end are removed and counted, so a capture that
    keeps failing cannot grow the spool. The two new events are valid lines (not malformed).
- **FR-002 Commit after store.** Capture stores a session's records, then commits the session. A capture that fails
  or is interrupted before the commit leaves the session for the next start; records already stored are not stored
  again (FR-003).
- **FR-003 Key (D1).** Each record carries tags `origin:capture`, `origin-session:<session id>`,
  `origin-record:<uuid>` (the failing `tool_result` entry's `uuid`), `origin-extractor:failed-then-fixed` and
  `origin-version:<n>`, and is stored with `session_id` = the captured session and `source` = `capture`. Once
  per session, before storing, capture lists the store's records with that `session_id` and `source=capture`
  (metadata only, filtered in the store) and skips any extracted record whose record and extractor tags match one
  of them, whatever its `origin-version`: the version is not part of the key. Identical content is also deduplicated by `retain()`.
- **FR-004 Port and adapter.** `TranscriptReaderPort.read(path)` returns every session in one transcript file, each
  with its window and its main-thread tool steps in order: entry `uuid`, time, tool name, the input's `command`, `file_path` or `query`, `is_error`, whether
  it was denied, and the result text. The Claude Code adapter (`src/memkernel/transcripts/claude_code.py`) skips
  sidechain entries and unreadable lines. Capture takes the session it is capturing from the result. The #120 count reads
  each file of its folder through the port and merges sessions by id, as its own reader does today; it drops that
  reader and keeps its fixture test passing.
- **FR-005 Extractor: failed-then-fixed commands.** A **failure** is a `Bash` step with `is_error` true whose
  result starts with `Exit code ` (so a denial or a harness block, which never ran, is not one). A **pass** is a
  `Bash` step that has a result without `is_error` true; a step with no result (an interrupted session) is neither. If a later pass in the same session runs the same command, under the D7
  matching rule, one record is extracted. A command that prints an error but exits 0 is not a failure and is not
  captured; the README says so. Its content:
  - ``Command `<command>` failed: `<error line>`. It passed later in the same session, after: <fix steps>.``
    Each of the command, the error line and every fix step is collapsed to one line, with its backticks removed, so
    the quoting holds.
  - **The error line** is the last line of the result containing one of `ERROR_WORDS`, else its first non-empty
    line. `ERROR_WORDS` moves into `src/` and the count imports it, so a captured error is a stored error under the
    count's rule.
  - **The fix steps** are the `Bash` commands and the `Edit`/`Write` file paths between the failure and the passing
    run, in order, at most `CAPTURE_FIX_STEPS`; "no other step" when there are none.

  Only structured fields and the failing command's own output are used, never text from other tools or web results
  (#59). Type `observation`, tier short-term, default importance. Each passing run closes the failures of that command
  before it: they give one record, keyed by the last of them. A command that fails, passes, fails and passes again
  gives two records.
- **FR-006 Redaction (D4).** Before storing, every command, error line and file path is redacted: each match is
  replaced with `[REDACTED]`. Best-effort; the README says what it covers and that other shapes are stored as
  written. Patterns:
  - `KEY=`, `TOKEN=`, `SECRET=`, `PASSWORD=` assignments (the name containing the word, any case) and `.env`-style
    lines of that shape: the value;
  - `Authorization:` headers: the value;
  - token prefixes `AKIA`, `ghp_`, `gho_`, `github_pat_`, `sk-`, `xox`: the token;
  - private key blocks (`-----BEGIN ... PRIVATE KEY-----` to its `END` line);
  - credentials in URLs (`scheme://user:password@`): the user and password;
  - long random-looking strings: 32 or more characters of `[A-Za-z0-9+/=_-]` with letters and digits both present,
    not all hexadecimal, so git SHAs and dashless UUIDs are kept. Other long identifiers (base64 data, generated
    names) can still be redacted: a false positive costs a word in the record, a miss would store a secret.

  Redaction is applied to the extracted fields before the record content is composed, so unredacted text is never
  passed to `retain()`. Each command and error line is then cut to `CAPTURE_TEXT_MAX` characters.
- **FR-007 When capture runs (D2, D3, D6).** With capture off, no capture code runs and the spool behaves as today:
  `drain()` removes every ended session, writes no `reported` or `capture_missed` line, and opens no transcript.
  With capture on: at normal startup, after the drain and before `consolidate()`, when
  `MEMKERNEL_CAPTURE` is on and the store is persistent. Sessions are taken oldest end first. Capture stops starting
  sessions once `CAPTURE_TIME_BUDGET` has passed or `CAPTURE_MAX_RECORDS` records were stored this run. The budget is
  a soft stop: a session already started is finished, so the run can pass the budget by one session, bounded by
  `CAPTURE_TRANSCRIPT_MAX_BYTES` and `CAPTURE_SESSION_MAX_RECORDS`. The hook templates set no timeout, so Claude
  Code's default for command hooks (60 seconds) applies to the whole SessionStart hook;
  the 3-second budget leaves most of it to loading the store and model and to `consolidate()`. Sessions not reached stay for the
  next start.
- **FR-008 Missing or unreadable transcript.**
  - **Missing or unreadable** (no `transcript_path`, or a path that is not a readable regular file): one
    `capture_missed` line. At the `CAPTURE_MISS_LIMIT`th miss, the session is committed (removed) and counted.
  - **Too large** (over `CAPTURE_TRANSCRIPT_MAX_BYTES`): unreadable, and since the size will not shrink, the session
    is committed (removed) at once, with no retries, and counted with the unreadable ones. The size is checked with
    a `stat()` before any read, so the file is never read. A file that grows past the cap after the `stat()` is
    read only up to the cap and then treated as too large: committed at once and counted, with the partial read's
    time counted against the budget. A transcript
    under the cap is read in full, and its read time counts against `CAPTURE_TIME_BUDGET` like the rest of that
    session's capture (the soft stop of FR-007). A session with no `started` line is committed without capture.
- **FR-009 Startup report.** When capture ran or dropped anything, the previous-sessions block gains one line:
  records stored, sessions captured, sessions left for the next start, and transcripts given up on.
- **FR-010 Promotion candidates (D5).** `consolidate()` leaves out records tagged `origin:capture`, for the startup
  block and the MCP tool alike. Captured records are otherwise ordinary memories: `recall`, `list_memories`, the
  startup context and `promote` see them, they expire under `observation_ttl_days` (7) like any short-term
  observation (memkernel has no count-based eviction), and every hook block quotes them as stored memory (#85), as it quotes
  every memory.
- **FR-011 #120 count.** The count reads transcripts through the adapter and reports, for stored errors from records
  tagged `origin:capture`, the same outcomes (shown, missed, other store, unknown) apart from the agent-stored ones.
- **FR-012 Settings and docs.** `MEMKERNEL_CAPTURE` (bool, default `false`) in the README configuration table, with
  what is read and stored, the redaction coverage and its limits. README hooks section: capture at startup.
  CHANGELOG under Added.

## Constraints / What NOT to Build

- No other extractors, no supersede suggestions, no canonical hashing (S3); no readers for other tools (#107).
- No transcript excerpts beyond the error line (#59 D3); no model-written text (#59 D4).
- No automatic promotion of captured records; no new MCP tool; no new runtime dependency.
- No detached worker: capture runs inside the startup hook.
- No version supersede and no re-scan of committed sessions (D1).
- Capture never holds the spool lock while it reads or stores, so the SessionEnd hook's 1.5-second budget is
  unaffected; `commit()` takes the lock only to rewrite the file.

## Key Entities

- **Captured record:** a short-term `observation` with the FR-003 tags.
- **Key:** (session, record UUID, extractor), from the tags.
- **Tool step:** what the adapter returns per tool call (FR-004).

## Success Criteria

- **SC-1** Fixtures cut from real transcripts (`fixtures/`, copied by the build into the test tree):
  - `failed-then-fixed.jsonl` (a `pytest` run exits 1, a test file is edited, the same run passes) yields one record
    with the FR-005 content and FR-003 tags;
  - `not-captured.jsonl` (a denial, a harness block, and an error printed with exit status 0) yields none;
  - a failure with no passing rerun and a sidechain failure yield none; fail, pass, fail, pass yields two.

  The cut keeps the fields the adapter reads, with `is_error` and the `Exit code` prefix unchanged, and shortens
  results longer than 600 characters. A test asserts the fixtures still hold the `Exit code 1` failure and the
  passing rerun's `is_error: false`.
- **SC-2** A capture killed after storing and before the commit, then rerun, stores nothing new; one killed before
  storing stores the record on the next start. Running capture twice on one session stores each signal once. A capture
  interrupted before the commit and retried after an upgrade (a higher `origin-version`) stores nothing for the
  records already captured. A session committed under one version, then an upgrade and a restart: nothing new is
  stored for it.
- **SC-3** With capture off, no transcript is opened and the spool behaves as on `main` (existing spool tests pass
  unchanged); with capture on, an unsaved session is reported once, though it stays in the spool until committed.
- **SC-4** A session with a missing transcript is dropped at the `CAPTURE_MISS_LIMIT`th start and counted in the
  startup report; an oversized one is dropped at the first start, without being read, and counted.
- **SC-5** Capture stops at `CAPTURE_MAX_RECORDS` and when the time budget has passed (an injected clock); the rest
  is captured at the next start.
- **SC-6** Each FR-006 pattern is redacted in a command, an error line and a file path.
- **SC-7** `consolidate()` never returns a captured record as a candidate; a captured record in the startup context
  is inside a stored-memory element.
- **SC-8** The #120 count runs on the adapter, its fixture test passes, and a captured error is reported apart from
  agent-stored ones.
- **SC-9** Fast suite, ruff, mypy strict, coverage ≥ 80%; MCP tool set unchanged.

## Decisions (the owner's, 2026-11-16)

- **D1 Key.** (session, record UUID, extractor), with the extractor version as a tag. No version supersede; a
  session is captured once, under the version installed then.
- **D2 Default.** Capture is off by default.
- **D3 Where it runs.** In the startup hook, with a time budget and a per-run record cap; the spec sets both (D6).
- **D4 Redaction.** The listed shapes plus token prefixes, private key blocks, credentials in URLs and `.env`-style
  lines; stated as best-effort.
- **D5 Promotion candidates.** Captured records stay out.

- **D6 Values.** The table below, proposed by this spec, approved by the owner on 2026-11-16.

## D7 The command-matching rule (open)

[NEEDS CLARIFICATION]: Which later command counts as a rerun of the failed one? The yield fact above shows the exact
rule finds 2 pairs in 289 failures. Options:
- **Exact** (whitespace collapsed): precise; finds almost nothing.
- **Exact after removing a trailing output filter** (` | tail …`, ` | head …`, ` | grep …`, `2>&1`): still precise;
  12 pairs.
- **The same program and target** (for example the same `pytest` path or `ruff` path): more pairs, but needs a
  per-tool definition of "target".

Recommendation: exact after removing a trailing output filter. It keeps the record trustworthy, and the yield is
measured again on real use through the #120 count before anything looser is built.

## D6 Values (approved)

Module constants in `capture.py`, not settings, so the configuration table grows by one row:

| Constant | Value | Why |
|---|---|---|
| `CAPTURE_TIME_BUDGET` | 3 seconds | The startup block already loads the store and model; 3 s keeps the hook's added time small. |
| `CAPTURE_MAX_RECORDS` | 20 per run | Each record is embedded once; 20 bounds the cost and the short-term store's growth. |
| `CAPTURE_SESSION_MAX_RECORDS` | 5 per session | One noisy session cannot take the whole run. |
| `CAPTURE_MISS_LIMIT` | 3 starts | A transcript written late gets two more chances; a deleted one leaves within three starts. |
| `CAPTURE_TRANSCRIPT_MAX_BYTES` | 50 MB | Reading a larger file could pass the budget on its own. |
| `CAPTURE_TEXT_MAX` | 300 characters | One error line or command, not an excerpt (#59 D3). |
| `CAPTURE_FIX_STEPS` | 5 | Enough to say what fixed it, short enough for a memory line. |

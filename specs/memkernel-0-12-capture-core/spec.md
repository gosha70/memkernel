# Spec: capture core, failed-then-fixed commands from ended sessions' transcripts (#134)

Status: draft, 2026-11-16. Decisions D1–D8 are the owner's (2026-11-16; D6's values proposed by this spec and
approved; D1 amended by the owner on 2026-11-16 after the review of #135, with amendments R1–R6; R7–R13 by the owner on 2026-11-17, from DIADE's report on #112 and the review of #135 at `0138a5f`).

## Checked facts (`main` at `7f26012`, memkernel 0.9.0)

- **The spool** (`session_spool.py`): `drain()` removes every ended session, other than the current one, and
  returns only the windows with no checkpoint (`DrainResult.unsaved`); the "previous sessions" block lists them,
  once, because they are removed. `SessionWindow` has no `transcript_path`, though the SessionEnd hook writes one on
  the `ended` line (`templates/hooks/session-end.py`). Unended sessions older than `SPOOL_UNENDED_MAX_AGE` (7 days)
  are removed and counted. A line whose event is not `started` or `ended` is removed as malformed.
- **The spool is unlocked without `fcntl`** (Windows): `session_spool.locked()` then does nothing, so concurrent
  appends and rewrites can lose lines (`session_spool.locking()` reports it).
- **A `retain()` dedup hit rewrites provenance** (`services.py`, `_refresh_existing`): identical content and type
  return the existing record, with its `session_id` replaced and its `timestamp` set to now, and tags merged. The
  #120 count judges a stored error by that timestamp (`count.py`, `stored_at`): a session that starts before it is
  not a repeat.
- **The drain runs only at normal startup** (`on_session_start`, `source == "startup"`), before `consolidate()`.
- **The SessionEnd hook has a 1.5-second budget** and imports only the settings; it holds the spool lock while it
  appends.
- **Claude Code's transcript** (JSONL, one entry per line; checked on a local transcript): each entry has `uuid`,
  `sessionId`, `timestamp` and `isSidechain`. A tool result is a `tool_result` part of a user message, with
  `tool_use_id`, `content` and `is_error`; a denied tool call's entry also carries `toolDenialKind`. A `tool_use`
  part has `id`, `name` and `input` (`command` for `Bash`, `file_path` for `Edit`/`Write`). **One entry can carry
  several tool results** under one `uuid`: 941 of the 24,466 entries with tool results in the 65 local transcripts
  do; `tool_use_id` differs per result, and no entry `uuid` repeats.
- **`is_error` on real transcripts** (checked 2026-11-16 on the 65 local Claude Code transcripts of the owner's
  projects):
  - a `Bash` command that exits non-zero has `is_error: true`, and its content starts with `Exit code <n>`;
  - a command that prints an error but whose last exit status is 0 has `is_error: false`: for example a heredoc
    `python3` script that raised `AssertionError`, followed by commands that succeeded (in `fixtures/not-captured.jsonl`);
  - `is_error: true` also marks calls that never ran: permission denials (with `toolDenialKind`) and harness blocks,
    whose content starts with `<tool_use_error>`;
  - some results have no `is_error` key (an `Edit` result, for example); absent means false;
  - entries without a message (`last-prompt`, `api-request` and others) are interleaved with the conversation.
- **Yield of the matching rule** (same transcripts): 289 `Bash` results with a non-zero exit, main thread only.
  - **The D7 rule** (trailing `| tail`, `| head`, `| grep` and `2>&1` removed): a later passing run follows **2**
    of them. In **1**, the passing run's exit status is the command's own; that pair is the one cut into
    `fixtures/failed-then-fixed.jsonl`. The other passed through `2>&1 | tail -20` without `pipefail`, so its
    exit status was `tail`'s.
  - **With D7's failure rule as well** (a failure's non-zero exit must be the command's own): 249 of the 289 are
    failures, and the result is still **1** pair, the same one.
  - **Exact** command (whitespace collapsed): 2, the same two.
  - An earlier count of 12 used a looser rule that dropped everything after the **first** pipe or `2>&1`, so
    different commands matched (for example `git diff --stat | tail -1 && python3 …` and `git diff --stat`). It
    measured nothing D7 uses.
  - The command's **first two words** (after `cd … &&` and `VAR=…` prefixes): 193, but two words such as
    `poetry run` or `git push` do not identify a command.
- **The #120 reader** (`eval/repeat-mistakes/transcripts.py`) reads a folder of transcripts by `sessionId`: each
  session's window, its `Bash` outputs and its `recall` calls. The count (`count.py`) treats a memory's
  backtick-quoted span containing one of `ERROR_WORDS` as a stored error, a single word such as `ValueError`
  included. It counts any later `Bash` output that contains the span as a repeat, whether or not the command
  failed, so a `cat NOTES.md` that quotes the stored error is a repeat. Its evidence does not name the command.
  (Reported by DIADE on #112, issuecomment-6940516688, and checked against `count.py` at `7f26012`.)
- **Subagent transcripts** are written to `<project folder>/<sessionId>/subagents/agent-*.jsonl`, with
  `isSidechain: true` and the parent's `sessionId` (checked 2026-11-17: 228 such files in the local transcripts;
  each of the 112 whose first line has a `sessionId` names its parent folder's session, and each of the same 112
  has an `agentId` equal to the `<id>` in its file name `agent-<id>.jsonl`). The #120 reader globs
  `*.jsonl` in the folder only, so it never reads them (DIADE, the same comment).
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
- **FR-003 Key (D1, R2) and identity (R1).** Each record carries tags `origin:capture`,
  `origin-session:<session id>`, `origin-call:<tool_use_id>` (the failing result's `tool_use_id`),
  `origin-extractor:failed-then-fixed` and `origin-version:<n>`, and is stored with `session_id` = the captured
  session and `source` = `capture`. Once per session, before storing, capture lists the store's records with that
  `session_id` and `source=capture` (metadata only, filtered in the store) and skips any extracted record whose call
  and extractor tags match one of them, whatever its `origin-version`: the version is not part of the key.
  - **No content dedup (R1).** Captured records are stored with `retain()`'s content dedup off, so the key alone is
    their identity: an identical record from another session is a new record, and a stored record's `session_id`,
    `timestamp` and tags are never rewritten by a later capture. `retain()` gains the keyword this needs; agent
    writes are unchanged.
- **FR-004 Port and adapter.** `TranscriptReaderPort.read(path, include_sidechains=False)` returns every session in
  one transcript file, each with its window and its tool steps in order (main-thread only by default): entry
  `uuid`, `tool_use_id`, time, tool name, the input's `command`, `file_path` or `query`, `is_error`, whether it was
  denied, the result text, `sidechain` (bool, the entry's `isSidechain`) and `agent_id` (R12: the entry's `agentId`,
  else the `<id>` of the file name `agent-<id>.jsonl`; empty on the main thread). The Claude Code adapter (`src/memkernel/transcripts/claude_code.py`) skips
  unreadable lines, and sidechain entries unless `include_sidechains` is true. Capture reads main-thread steps only. Capture takes the session it is capturing from the result; a readable file without that session is a miss
  (FR-008, R5). The #120 count (R7) reads every
  transcript under its folder, the subagent files `<sessionId>/subagents/*.jsonl` included, through the port with
  `include_sidechains=True`, and merges sessions by id, so a subagent's steps belong to its parent session but keep
  their `sidechain` flag and `agent_id`. **Recalls and repeats stay with their thread (R12):** a subagent's `recall`
  calls, and the recall-log records paired with them, belong to that subagent; a main-thread repeat is judged only
  against main-thread recalls and the parent's hook blocks, and a subagent repeat only against that subagent's
  recalls (a subagent gets no hook block). It drops
  its own reader and keeps its fixture test passing.
- **FR-005 Extractor: failed-then-fixed commands.** A **failure** is a `Bash` step with `is_error` true whose
  result starts with `Exit code ` (so a denial or a harness block, which never ran, is not one), and whose non-zero
  exit status is the command's own (D7). A **pass** is a
  `Bash` step that has a result without `is_error` true, and whose exit status is the command's own (D7); a step
  with no result (an interrupted session) is neither. If a later pass in the same session is a rerun of the failed
  command (D7), one record is extracted. A command that prints an error but exits 0 is not a failure and is not
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
  `MEMKERNEL_CAPTURE` is on and the store is persistent.
  - **One capture at a time (R3).** Capture takes `capture.lock` beside the project's spool file
    (`MEMKERNEL_STATE_DIR/session-spool/<project_id>/`) with a non-blocking exclusive lock, and holds it from the
    key lookup through storing and the commit. If another startup holds it, this start skips capture (no wait, no
    report line). The spool lock is separate and is still taken only by `commit()` and the drain, so the SessionEnd
    hook's 1.5-second budget is unaffected. The lock sits beside the spool because a session is only ever in its
    own project's spool.
  - **No locking, no capture (R6).** Where locks are unavailable (`session_spool.locking()` false, Windows), capture
    stays off even with `MEMKERNEL_CAPTURE` on, with one warning per process, and the spool behaves as with
    capture off.
  - **The per-session cap (R4).** A session keeps its first `CAPTURE_SESSION_MAX_RECORDS` signals in transcript
    order; the rest are dropped when the session is committed, never deferred, and counted in the startup report.
  - **Order and budget.** Sessions are taken oldest end first. Capture stops starting sessions once
    `CAPTURE_TIME_BUDGET` has passed or `CAPTURE_MAX_RECORDS` records were stored this run. The budget is a soft
    stop: a session already started is finished, so the run can pass the budget by one session, bounded by
    `CAPTURE_TRANSCRIPT_MAX_BYTES` and `CAPTURE_SESSION_MAX_RECORDS`. The hook templates set no timeout, so Claude
    Code's default for command hooks (60 seconds) applies to the whole SessionStart hook; the 3-second budget leaves
    most of it to loading the store and model and to `consolidate()`. Sessions not reached stay for the next start.
- **FR-008 Missing or unreadable transcript.**
  - **Missing or unreadable** (no `transcript_path`, a path that is not a readable regular file, or a readable file
    that does not contain the session (R5)): one `capture_missed` line. A file that contains the session but yields
    no signal is not a miss: the session is committed. At the `CAPTURE_MISS_LIMIT`th miss, the session is committed (removed) and counted.
  - **Too large** (over `CAPTURE_TRANSCRIPT_MAX_BYTES`): unreadable, and since the size will not shrink, the session
    is committed (removed) at once, with no retries, and counted with the unreadable ones. The size is checked with
    a `stat()` before any read, so the file is never read. A file that grows past the cap after the `stat()` is
    read only up to the cap and then treated as too large: committed at once and counted, with the partial read's
    time counted against the budget. A transcript
    under the cap is read in full, and its read time counts against `CAPTURE_TIME_BUDGET` like the rest of that
    session's capture (the soft stop of FR-007). A session with no `started` line is committed without capture.
- **FR-009 Startup report.** When capture ran or dropped anything, the previous-sessions block gains one line:
  records stored, sessions captured, sessions left for the next start, transcripts given up on, and signals dropped
  over the per-session cap.
- **FR-010 Promotion candidates (D5).** `consolidate()` leaves out records tagged `origin:capture`, for the startup
  block and the MCP tool alike. Captured records are otherwise ordinary memories: `recall`, `list_memories`, the
  startup context and `promote` see them, they expire under `observation_ttl_days` (7) like any short-term
  observation (memkernel has no count-based eviction), and every hook block quotes them as stored memory (#85), as it quotes
  every memory.
- **FR-011 #120 count.** The count reads transcripts through the adapter (FR-004) and reports, for stored errors
  from records tagged `origin:capture`, the same outcomes (shown, missed, other store, unknown) apart from the
  agent-stored ones. Three fixes to how it counts (R8, R9):
  - **A repeat needs a failed run (R8).** A later `Bash` output is a repeat only when its run is a failure under
    FR-005 (`is_error` true, an `Exit code` result, and the command's own exit status), so a note or listing read
    through `Bash` (`cat`, `grep`, `git diff`) is not one.
  - **The evidence names the command (R8).** Each repeat's evidence includes the failing run's command (redacted
    per FR-006, cut to `CAPTURE_TEXT_MAX`).
  - **A stored error has more than one word (R9).** A backticked span is a stored error only when it contains one
    of `ERROR_WORDS` and more than one word, so a bare `ValueError` or `Exception` is not one. A word is a
    whitespace-separated token after `collapse()`, so `pkg.mod.FooError` is one word. `ERROR_WORDS`
    and this rule live in `src/` with the extractor (FR-005), and the count imports them.
  - **Subagent repeats are reported apart (R10).** A subagent does not get its parent's startup context, so a repeat
    found in a subagent's steps is marked `(subagent)` and counted on its own line of the report, never as a
    memory that was shown and missed.
  - The README's "What it cannot detect" list gains (#136): a prose lesson with no quoted error; a single-word
    signature; output that is not from a failed run (an error printed with exit status 0, a note read through
    `Bash`, and above all a command piped into a filter without `pipefail`, such as `… 2>&1 | tail -20`, whose
    real failure exits 0 and is not counted under R8); and that a multi-word code fragment such as `except Exception:` still counts as a signature (R11).
- **FR-012 Settings and docs.** `MEMKERNEL_CAPTURE` (bool, default `false`) in the README configuration table, with
  what is read and stored, the redaction coverage and its limits, that identical captured text from two sessions is
  stored twice and can be shown twice until it expires (R13), and that capture stays off where locking is
  unavailable (Windows, R6). README hooks section: capture at startup.
  CHANGELOG under Added. Both the README and the CHANGELOG entry say, per D8, that the failed-then-fixed extractor
  captures rarely (1 pair in 289 failures across 65 transcripts) and that S3 adds the extractors with real yield.

## Constraints / What NOT to Build

- No other extractors, no supersede suggestions, no canonical hashing (S3); no readers for other tools (#107).
- No transcript excerpts beyond the error line (#59 D3); no model-written text (#59 D4).
- No automatic promotion of captured records; no new MCP tool; no new runtime dependency.
- No detached worker: capture runs inside the startup hook.
- No version supersede and no re-scan of committed sessions (D1).
- No "same program and target" matching (D7).
- Capture never holds the spool lock while it reads or stores, so the SessionEnd hook's 1.5-second budget is
  unaffected; `commit()` takes the lock only to rewrite the file. Capture's own lock is `capture.lock` (R3).
- No capture without locking (R6).

## Key Entities

- **Captured record:** a short-term `observation` with the FR-003 tags.
- **Key:** (session, `tool_use_id`, extractor), from the tags (D1 as amended, R2).
- **Tool step:** what the adapter returns per tool call (FR-004).

## Success Criteria

- **SC-1** Fixtures cut from real transcripts (`fixtures/`, copied by the build into the test tree):
  - `failed-then-fixed.jsonl` (a `pytest` run exits 1, a test file is edited, the same run passes) yields one record
    with the FR-005 content and FR-003 tags;
  - `not-captured.jsonl` (a denial, a harness block, and an error printed with exit status 0) yields none;
  - a failure with no passing rerun and a sidechain failure yield none; fail, pass, fail, pass yields two;
  - a rerun that exits 0 through a trailing `| tail` without `pipefail` is not a pass, and yields none; the same
    rerun with `set -o pipefail` yields one;
  - `cmd | grep X` exiting 1 because `grep` matched nothing, then `cmd | grep X` or `cmd` passing, yields none: the
    exit status was `grep`'s, so it is not a failure; the same with `set -o pipefail`, where `cmd` itself failed,
    yields one.

  The cut keeps the fields the adapter reads, with `is_error` and the `Exit code` prefix unchanged, and shortens
  results longer than 600 characters. A test asserts the fixtures still hold the `Exit code 1` failure and the
  passing rerun's `is_error: false`.
- **SC-2** A capture killed after storing and before the commit, then rerun, stores nothing new; one killed before
  storing stores the record on the next start. Running capture twice on one session stores each signal once. A capture
  interrupted before the commit and retried after an upgrade (a higher `origin-version`) stores nothing for the
  records already captured. A session committed under one version, then an upgrade and a restart: nothing new is
  stored for it.
  - **Two sessions with identical extracted content (R1)** give two records, each with its own session and
    timestamp; capturing the second leaves the first record's `session_id`, `timestamp` and tags unchanged.
  - **A batched entry (R2)** holding two failing results under one `uuid`, both later fixed, gives two records; a
    capture interrupted after storing one of them stores only the other on the retry.
  - **Two processes (R3)** running startup capture at once on the same spool store each signal once; the one that
    did not get `capture.lock` skips capture.
- **SC-3** With capture off, no transcript is opened and the spool behaves as on `main` (existing spool tests pass
  unchanged); with capture on, an unsaved session is reported once, though it stays in the spool until committed.
- **SC-4** A session with a missing transcript is dropped at the `CAPTURE_MISS_LIMIT`th start and counted in the
  startup report; an oversized one is dropped at the first start, without being read, and counted; a readable
  transcript without the session counts as a miss (R5), and one with the session but no signal is committed.
- **SC-5** Capture stops at `CAPTURE_MAX_RECORDS` and when the time budget has passed (an injected clock); the rest
  is captured at the next start. A transcript with `CAPTURE_SESSION_MAX_RECORDS` + 1 signals stores the first
  `CAPTURE_SESSION_MAX_RECORDS`, commits the session, and reports one dropped (R4).
- **SC-5b** With locking unavailable (`locking()` patched false) and `MEMKERNEL_CAPTURE` on, no transcript is opened,
  the spool behaves as with capture off, and one warning is logged (R6).
- **SC-6** Each FR-006 pattern is redacted in a command, an error line and a file path.
- **SC-7** `consolidate()` never returns a captured record as a candidate; a captured record in the startup context
  is inside a stored-memory element. Two captured records with identical text from two sessions are two records
  (R1), so a hook block or `recall` can show the same lesson twice until the TTL expires them; the README says so
  (R13).
- **SC-8** The #120 count runs on the adapter, its fixture test passes, and a captured error is reported apart from
  agent-stored ones. On a fake transcript folder:
  - a session that only runs `cat NOTES.md`, whose output quotes the stored error, has no repeat (R8);
  - a session whose subagent (`<sessionId>/subagents/agent-1.jsonl`, sidechain lines) runs the failing command has
    a repeat, attributed to the parent session, marked `(subagent)` and reported on its own line, whose evidence
    names the command (R7, R8, R10);
  - a subagent recalls the memory, then the parent's main thread repeats the error: the repeat is not "shown" (R12);
  - a memory whose only backticked error text is `ValueError` has no stored error (R9).
  DIADE's fixture transcripts and expected outcomes, landed with the build (see the note below), pass.
- **SC-9** Fast suite, ruff, mypy strict, coverage ≥ 80%; MCP tool set unchanged.

## Decisions (the owner's, 2026-11-16)

- **D1 Key.** (session, `tool_use_id`, extractor), with the extractor version as a tag. No version supersede; a
  session is captured once, under the version installed then. (Amended by the owner, R2: the key named the record
  UUID, which several results in one entry share.)
- **D2 Default.** Capture is off by default.
- **D3 Where it runs.** In the startup hook, with a time budget and a per-run record cap; the spec sets both (D6).
- **D4 Redaction.** The listed shapes plus token prefixes, private key blocks, credentials in URLs and `.env`-style
  lines; stated as best-effort.
- **D5 Promotion candidates.** Captured records stay out.

- **D6 Values.** The table below, proposed by this spec, approved by the owner on 2026-11-16.
- **D7 Rerun and pass.**
  - **A rerun** is the same command, whitespace collapsed, after removing trailing `| tail …`, `| head …`,
    `| grep …` and `2>&1` (the owner's words). This spec's reading: a trailing filter is a final pipeline segment that contains no other `|`, `;`, `&`, `<`
    or `>`; removal repeats until none is left, so `cmd 2>&1 | tail -20` becomes `cmd`.
  - **A run counts as passed, or as failed,** only when its exit status is the command's own: the command has no
    trailing filter pipe (a trailing `2>&1` alone does not change the status), or it sets `pipefail`
    (`set -o pipefail`). The owner's decision for passes, extended to failures by the owner on 2026-11-16.
  - **"Same program and target" matching is not built** for now.
- **D8 Yield.** S2 ships as the pipeline's first slice: the spool, the reader, the key, redaction, the startup run
  and the #120 hookup, with failed-then-fixed commands as its one extractor. That extractor captures rarely: 1 pair
  in 289 failures across 65 transcripts (the yield fact above). S3 adds the extractors with real yield. The README
  says both (FR-012).

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

## Amendments (the owner's, 2026-11-16, from the review of #135 at `ce8de50`)

- **R1** Captured records skip `retain()`'s content dedup, so a later capture never rewrites a stored record's
  session, timestamp or tags (FR-003, SC-2).
- **R2** The key uses the failing result's `tool_use_id`, not the entry `uuid` (D1, FR-003, FR-004, SC-2).
- **R3** One capture at a time: a non-blocking `capture.lock` held from lookup through commit (FR-007, SC-2).
- **R4** Signals over the per-session cap are dropped at commit and counted (FR-007, FR-009, SC-5).
- **R5** A readable transcript without the session is a miss (FR-004, FR-008, SC-4).
- **R6** No capture where locking is unavailable (FR-007, SC-5b, README).

## Amendments (the owner's, 2026-11-17, from DIADE's report on #112 and the review of #135 at `0138a5f`, tracked in #136)

- **R7** The #120 count reads subagent transcripts: the subfolder files and their sidechain lines, through an
  `include_sidechains` option that only the count turns on (FR-004, SC-8).
- **R8** A repeat counts only when the run failed under FR-005's definition, and each repeat's evidence names the
  command (FR-011, SC-8).
- **R9** A stored error is a backticked span with an error word and more than one word (FR-011, SC-8). Single-word
  signatures are dropped, not reported separately.
- **R10** Subagent repeats are marked `(subagent)` and reported apart, since a subagent has no startup context
  (FR-011, SC-8).
- **R11** "What it cannot detect" says a multi-word code fragment (`except Exception:`) still counts as a signature
  (FR-011).

- **R12** Each tool step carries `sidechain` and `agent_id`; the count keeps a subagent's recalls and repeats with
  that subagent (FR-004, SC-8).
- **R13** The README and SC-7 say identical captured text from two sessions is shown twice until it expires
  (FR-012, SC-7).

These fixes are tracked in #136, which the S2 build fixes.

**Order.** DIADE's tests show the bugs, so a tests-only PR against `main` would fail until the fixes land, and tests
are never skipped or weakened to get green. So DIADE contributes the fixture transcripts and expected outcomes, and
they land in the S2 build PR, credited to DIADE (co-author or attribution), or as a PR against the build branch.
There they guard the reader's move into `src/` (FR-004) as well as the fixes.

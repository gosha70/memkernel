# Spec: a recall log and a repeated-mistake count (#120)

Status: approved by the owner, 2026-11-11 (decisions D1–D6 below).

## Checked facts (`main` at `4ac307e`, memkernel 0.9.0)

- **Who calls `recall`.** The MCP tool (`src/memkernel/mcp/tools/memory.py`, `recall`) and the session-start hook
  path (`src/memkernel/lifecycle.py`, two calls: the context lines and the checkpoint). The hook knows Claude
  Code's session id (`on_session_start(source, session_id)`); the MCP server does not.
- **The spool cannot map sessions after the fact.** `session_spool.drain()` removes every ended session at the
  next `startup`, so its windows are gone before any count runs. #120 proposes mapping through the spool; this
  spec uses the transcripts instead (D2).
- **Claude Code transcripts keep what the count needs from the tool side:** every tool call and its result, with a
  timestamp and the session id, and the SessionStart hook's injected text as an attachment (checked in this
  repo's own transcripts under `~/.claude/projects/`). One transcript file is one session.
- **memkernel keeps no per-call record of what `recall` returned;** only `access_count` and `last_accessed`.
- **State files** live under `MEMKERNEL_STATE_DIR` (`session-spool/<project_id>/`, the wiki sync ledger), and
  nothing is written for an in-memory store (empty `chroma_persist_path`). The spool locks with `fcntl`.

## User Scenarios

1. A maintainer enables `MEMKERNEL_RECALL_LOG=1` for a build. Each `recall` from the agent or the session-start
   hook leaves one line in the project's recall log. Nothing else changes.
2. After the build, they run `eval/repeat-mistakes/count.py` with the store, the recall log and the Claude Code
   transcript folder. It lists each repeat of a stored error message and its class, with counts, and states what
   it cannot detect.
3. With the log disabled (the default), no file is written and `recall` behaves exactly as before.

## Requirements

- **FR-001 Recall log (D1, D3, D4).** With `MEMKERNEL_RECALL_LOG=1` and a persisted store, each `recall` made by
  the MCP tool or the session-start hook appends one JSON line to
  `MEMKERNEL_STATE_DIR/recall-log/<project_id>/recall.jsonl`: `time` (UTC, ISO 8601), `origin` (`tool` or
  `hook`), `session_id` (the hook's; empty for `tool`), `query`, the filters as passed (`type`, `tier`,
  `session_id_filter`, `checkpoint_only`, `top_k`, `include_needs_review`, `order`), and `ref_ids`, in the order
  returned. The query is kept up to 2,000 characters. The file is created with mode `0600`. A write failure is
  logged once per process and never fails the `recall`.
- **FR-002 Off by default.** Disabled, or with an in-memory store, nothing is written and no directory is created.
- **FR-003 Bounded (D3).** Before each append, if the current file would pass `recall_log_max_bytes`, it is
  rotated: `recall.jsonl` becomes `recall.jsonl.1`, older files shift up, and files beyond `recall_log_max_files`
  are deleted.
- **FR-004 Settings.** `recall_log: bool = False` (`MEMKERNEL_RECALL_LOG`), `recall_log_max_bytes` (default
  5 MB per file) and `recall_log_max_files` (default 10), all in the README configuration table, with a note that
  the log stores query text and stays local.
- **FR-005 Counting script (D2, D5, D6).** `eval/repeat-mistakes/count.py` reads one or more stores (each with its
  recall log) and a Claude Code transcript folder, applies the rule in D5, classifies each repeat as in D6, and
  prints a report with counts, each repeat's evidence (memory `ref_id`, session id, the failure's timestamp, the
  matched text; for Missed, whether every recall's filters excluded the memory) and its limits. `--json` writes the same as a file.
- **FR-006 Transcript reader.** A small Claude Code transcript reader inside `eval/repeat-mistakes/`, documented
  as temporary until #59 Phase 2's reader exists.
- **FR-007 Docs.** A README section: enabling the log, running the count on your own build, and what it cannot
  detect: reworded or differently quoted errors (exact text only), failures outside `Bash` output, sessions whose
  recalls were not logged, recalls made through the library rather than the MCP tool or the hook, and ambiguous
  sessions (D2). CHANGELOG under `[Unreleased]`.

## Constraints / What NOT to Build

- No change to `recall`'s results, signature or ranking, to the MCP tools, or to stored records.
- No "mistake" memory type, no automatic correction, no model judging "the same mistake".
- No new runtime dependency. The counting script lives in `eval/`, not in the package.
- The script never reads notes, documents or memory content as evidence of a failure: only command output in the
  session's own tool results.

## Key Entities

- **Recall record:** one line of the recall log (FR-001).
- **Error signature:** a text extracted from a memory by D5's rule.
- **Repeat:** a later session whose own command output contains a signature.

## Success Criteria

- **SC-1** With the log enabled, each `recall` through the MCP tool and the hook leaves exactly one record with the
  fields in FR-001; disabled, or with an in-memory store, nothing is written.
- **SC-2** Rotation keeps at most `recall_log_max_files` files, each within `recall_log_max_bytes`.
- **SC-3** On a fixture with known repeats (one returned before the failure, one retrieval miss, one memory in a
  store the session never read, one session whose recalls are not logged), the script reports each in the right
  class. Also: a note or document that mentions the message is not counted; a recall made after the failure does
  not make it "shown"; a memory line with two backtick spans yields only the span with an error word; and a
  tool record that matches calls in two sessions is reported as ambiguous.
- **SC-4** The fast suite, ruff, mypy strict and coverage ≥ 80% pass; MCP tool set unchanged.

## Decisions (the owner's, 2026-11-11)

- **D1 Where to log.** Recalls made by the MCP tool and by the session-start hook, through one small `recall_log`
  module; `MemoryService.recall` keeps its signature. Recalls by other Python callers are not logged.
- **D2 Which session a recall belongs to.** `hook` records carry the session id. For a `tool` record, the script
  finds the transcript's own `recall` call: same query, within 5 seconds (the MCP server and Claude Code run on
  the same computer), paired one to one, nearest first. No
  match, or matches in more than one session: the session is unknown, never guessed. Session windows come from the
  transcripts; the spool is not used (checked facts).
- **D3 Size limit.** Both limits are settings: a maximum size per file (default 5 MB)
  and a maximum number of files (default 10), so at most 50 MB by default.
- **D4 Query text.** Stored as given, up to 2,000 characters; the log is opt-in and local.
- **D5 What counts as a stored error, and as a repeat.**
  - **Stored error:** text a memory quotes in backticks that contains an error word (`Error`, `Exception`,
    `Traceback`, `FAILED`, `fatal`). Example: a memory saying ``npm test fails with `Error: Cannot find module 'x'` ``
    stores the error `Error: Cannot find module 'x'`. Each such span is its own stored error; matching is
    case-sensitive.
  - **Repeat:** a later session whose own `Bash` output contains that exact text.
- **D6 What the report says about each repeat.** One of four outcomes:
  1. **Shown:** memkernel returned the memory to that session before the error happened again.
  2. **Missed:** the memory was in the store the session used, but memkernel did not return it before the error.
  3. **Other store:** the memory was in a store the session never used.
  4. **Unknown:** no log for that session, so it cannot be told.

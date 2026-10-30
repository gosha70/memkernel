# Spec: the wiring check on both import paths (#81), and spool pruning (#79 follow-up)

Origin: #81, the follow-up noted on #79, and the owner's go of 2026-10-30 (`origin/2026-10-30-go.md`). Facts are
in `plan.md`.

## User Scenarios
- **US1:** a maintainer runs the lc-wiki wiring check in the image, or in the dev venv with wiki-studio. Each
  environment checks the import path its users take, and the dev venv can check both.
- **US2:** a project whose sessions sometimes end without a SessionEnd line, after crashes or without the hook,
  keeps a bounded spool. It is told once when sessions keep ending without a record.

## Decisions (recommendations for the owner to confirm)
**W1. The wiring check runs both paths (#81 option C, as the owner recommended).** A new `--wiki-path` option:
- **`governed`:** after `wiki_export` in the source namespace, the check curates the exported page as a curator
  would, with wiki-studio, through the server's interpreter:
  1. promote an `update` patch-set setting `status: draft` to `status: stable`, with the page's base sha256.
     `approve` refuses a draft (wiki-studio's `promoter.py`, its approve checks).
  2. approve the page (`<python> -m wiki_studio --root … --wiki-dir … approve <page> --by wiring-check`).

  The transfer then carries the wiki, including its manifest and approval records. In the destination,
  `wiki_import` must report the page as imported, governed.
- **`ungoverned`:** the server runs with wiki-studio hidden: a stub `wiki_studio` package, first on the server's
  `PYTHONPATH`, raises `ModuleNotFoundError(name="wiki_studio")`, the only error memkernel treats as absence. This
  needs no product setting. Release B part 2c's governed and ungoverned modes are a separate spec. The import must
  report `"governed": false` and the page imported.
- **`both`:** runs the two legs in fresh namespaces, one after the other. Each step's name is prefixed with its
  leg, and the check passes only when both pass.
- **`auto` (the default):** `governed` when the server's interpreter has wiki-studio 0.7.0 or later, else
  `ungoverned`. So the image's run keeps today's meaning, and a dev-venv run takes the governed path.
- The report names the path(s) it ran.

**W2. Spool pruning (#79 follow-up).** At each `startup` drain:
- A session with no `ended` line whose newest line is older than `SPOOL_UNENDED_MAX_AGE` (a named constant, 7
  days) is removed. The current session is never removed.
- Such a session gets no "ended without a saved checkpoint" line, because its window never closed.
- If any were removed, the block says so once: "N earlier session(s) recorded no end (crashed, or session-end.py
  is not registered under SessionEnd)."
- The spool then holds at most the current session, sessions under 7 days old without an end, and ended sessions
  not yet drained.

## Requirements
- **FR-001 (W1):** `wiring_check.py` takes `--wiki-path {auto,governed,ungoverned,both}`, default `auto`, as W1
  describes. The governed leg marks the page stable through a promoted update, then approves it. `governed` fails with a clear step if the server's interpreter has no wiki-studio. `ungoverned`
  hides wiki-studio from the server process only.
- **FR-002:**
  - `tests/unit/test_wiring_check.py`'s slow test runs `both` in the dev venv.
  - A fast unit test covers the stub: an interpreter with the stub first on its path imports memkernel's bridge as
    "wiki-studio absent".
- **FR-003 (the 0.5 record):** the 0.5 records keep their sha256 and are not edited; they name the commit whose
  `wiring_check.py` they ran. The changed check gets a new sha256 wherever a future run records it.
- **FR-004 (W2):** `session_spool.drain` removes unended sessions older than `SPOOL_UNENDED_MAX_AGE` and returns
  how many it removed. `on_session_start("startup")` adds W2's one line under `### Previous sessions`, within
  that section's line cap. A malformed time still counts as a malformed line.
- **FR-005:** README (the hooks table's `session-end.py` row, W2's note) and CHANGELOG `[Unreleased]`.

## Constraints / What NOT to Build
- No memkernel setting to turn governance off (that is 2c). No change to the governed or ungoverned import.
- The 0.5 report, its calibration records and the frozen arms are not edited.
- No transcript capture (#59 Phase 2).

## Key Entities
- **Wiring leg:** `governed` or `ungoverned`, each with its own source and destination namespaces and steps.
- **`SPOOL_UNENDED_MAX_AGE`:** 7 days.

## Success Criteria
- **SC-1:** in the dev venv, `--wiki-path both` passes. The governed leg imports the approved page (`"governed":
  true`), and the ungoverned leg imports it with `"governed": false`.
- **SC-2:** `auto` picks `governed` with wiki-studio present and `ungoverned` without it. `governed` without
  wiki-studio fails with a step that names the reason.
- **SC-3:** the stub makes memkernel's `load_studio()` return `None` in the server's interpreter only.
- **SC-4:**
  - An unended session older than 7 days is removed at startup, with W2's one line.
  - One younger than 7 days is kept.
  - The current session is kept whatever its age.
  - An ended session is handled as before.
- **SC-5:** fast suite green, coverage ≥ 80 percent, ruff (including `eval/`) and mypy clean.

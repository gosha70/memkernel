---
feature_id: memkernel-0-5
status: draft
date: 2026-10-15
---

# Spec: memkernel 0.5 — evidence and wiki-studio

Two tracks. Track A makes wiki-studio the owner of the wiki schema, the
lint and health pass and the promote gate, behind an optional extra. Track B
answers issue #17 with a **maintainer-run supplemental evaluation** of the
four lifecycle claims, run by a minimal runner in this repository on tasks
in `agent-memory-bench`'s executable task format, preregistered and graded by
checkers with no LLM judge; entering memkernel as a retrieval arm of that
benchmark continues upstream in parallel and is not a release gate (amended
2026-10-16, option B; `origin/2026-10-16-option-b.md`). US1 shipped as
0.4.1; US2–US4 ship as 0.5.0.

## User Scenarios

### US1: A reader knows what MemKernel is, what it is not, and which wiki maintainer it pairs with (Priority: HIGH, release 0.4.1)

A README section states the four things MemKernel is and the four things it
is not, names the retrieval eval as the only current evidence and links #17.
Every mention of the working name `ai-wiki` becomes wiki-studio. CI proves
that what `WikiExporter` writes lints clean with the published wiki-studio.

### US2: wiki-studio is the wiki maintainer; memkernel is a client of it (Priority: HIGH, release 0.5.0)

With `pip install memkernel[wiki]`, `wiki_export` writes drafts through
wiki-studio's promote gate (lint-checked, atomic) and returns the lint and
health findings. Without the extra, behaviour is unchanged. memkernel's
copy of the schema is proven equal to wiki-studio's by a test.

### US3: The lifecycle claims can be measured reproducibly, by anyone, on a runner whose scope is fixed (Priority: HIGH, release 0.5.0)

`eval/lifecycle-suite/` holds a minimal runner, the four task groups in the
benchmark's executable task format, frozen per-arm persistence rules, a
credential-free demonstration with simulated events, count-based
diagnostics, a secret scan and the freeze verifier. A contributor can rerun
every published number from the committed configuration and records.

### US4: The project publishes its first lifecycle evidence, failures and nulls included (Priority: HIGH, release 0.5.0)

A calibration pilot proves feasibility (including a live compaction with
hooks recorded) and fixes the budget; a preregistration is committed and
announced; the measured run executes from a frozen code SHA; the report is
labelled as a maintainer-run supplemental evaluation and linked from the
README evidence line and the release notes.

### US5: memkernel enters agent-memory-bench as a retrieval arm (Priority: MEDIUM, not a release gate)

The upstream integration questions are answered, then an adapter is
contributed upstream. Any retrieval results are reported separately from the
lifecycle evaluation and never merged into its numbers.

## Requirements

### Track A — wiki-studio

- **FR-001**: Done before this spec was approved: PR #18 (merged as 94016f5) added the README section "What MemKernel is, and what it is not" (four "is" items, four "is not" items, an "Evidence" line naming `eval/run_eval.py` and #17 with results "per minor release") and the roadmap evidence item. US1 MUST NOT re-add or duplicate either; it only keeps them consistent with FR-002.
- **FR-002**: Every occurrence of `ai-wiki` in `README.md` (LLM wiki bridge section, Related projects table), `docs/roadmap.md` and a dated follow-up note in `docs/adr/ADR-008-llm-wiki-as-semantic-layer.md` MUST refer to wiki-studio (`https://github.com/gosha70/wiki-studio`, PyPI `wiki-studio`); the ADR body is otherwise unchanged. The roadmap 0.5 line MUST say "lint and health via wiki-studio", not "query".
- **FR-003**: `tests/unit/test_wiki.py` MUST gain a contract test that exports a decision, a convention and a procedure with `WikiExporter` into `tmp_path`, then runs `wiki_studio.api.lint(WikiPaths.for_root(tmp_path, wiki_dir=...), health=True)` and asserts zero violations and zero audit errors (health warnings are allowed and asserted to contain only `weak-orphan`). The test is skipped when `wiki_studio` cannot be imported. wiki-studio MUST be a dev dependency (`[tool.poetry.group.dev.dependencies]`), pinned `>=0.1,<1`.
- **FR-004**: CI MUST run the contract test. `.github/workflows/ci.yml` on `main` runs a plain `poetry install`, which installs the dev group, so the test runs inside the existing fast suite and the workflow file is NOT touched by this feature.
- **FR-005**: `pyproject.toml` MUST declare `wiki-studio = {version = ">=0.1,<1", optional = true}` and `[tool.poetry.extras] wiki = ["wiki-studio"]` (the lower bound rises to `>=0.2` only in the task that ships the promote gate, FR-007); `docs/adr/ADR-010-wiki-studio-as-wiki-maintainer.md` MUST record the decision (optional extra, stdlib-only dependency, what is adopted, what is not, the fallback without it); the README install section MUST show `pipx install "memkernel[wiki]"` and `pipx inject memkernel wiki-studio` for an existing install.
- **FR-006**: `src/memkernel/wiki/studio.py` MUST import `wiki_studio` lazily inside a helper that returns `None` when the package is absent; absence of an optional extra is normal and MUST NOT log anything. A warning is logged only when wiki-studio functionality was explicitly requested and cannot be served: `MEMKERNEL_WIKI_PROPOSALS_DIR` is set, or a caller passes `require_studio=True`. No module-level import; `core/` stays untouched. Because wiki-studio is always installed in CI as a dev dependency, the no-extra path MUST be tested by simulating the failed import (monkeypatching the helper's import to raise `ImportError`), and a test MUST read `pyproject.toml` and assert that `wiki-studio` is declared `optional = true` and listed only under the `wiki` extra (SC-1). Nothing in memkernel MUST ever call wiki-studio's `ingest`, `query` or any copilot-CLI backend; `lint(..., backend=None)` is the only call that could take a backend.
- **FR-007 (needs wiki-studio ≥ 0.2)**: With the extra at ≥ 0.2 installed, `WikiExporter.export()` MUST write the drafts as a wiki-studio patch-set through the public proposal API (`wiki_studio.api.propose(...)`) into the proposals directory and apply it with `wiki_studio.api.promote(...)`; a lint failure MUST leave the wiki untouched and be reported. The on-disk result for a clean export MUST equal the direct write (same page bodies, index and log entries) so `wiki_import` and 0.4 wikis are unaffected. Without the extra, or with wiki-studio < 0.2, the direct writer stays. New setting `wiki_proposals_dir: str = ""` (`MEMKERNEL_WIKI_PROPOSALS_DIR`, empty = wiki-studio's default resolution), documented in the README table. **Fallback (wiki-studio 0.2.0 not released when 0.5.0 ships)**: FR-005, FR-006 and FR-008 ship against `>=0.1`; FR-007 and FR-009 move to 0.5.1; the README says the gate is not yet active.
- **FR-008 (works with wiki-studio 0.1)**: `ExportReport` MUST gain `lint: LintSummary | None` filled from `wiki_studio.api.lint(paths, health=True)` after a successful export (direct or gated), `None` without the extra. `LintSummary` MUST preserve wiki-studio's public shapes: `violations: list[str]`, `audit_errors: list[str]`, `pages_checked: int`, `health: list[HealthItem] | None` with `HealthItem(kind: str, severity: str, pages: list[str], description: str)` copied field for field from `wiki_studio.proposal.HealthFinding`; no renaming or flattening. The `wiki_export` MCP tool MUST return it under `"lint"`, and `null` plus `"lint_hint": "install memkernel[wiki] for lint and health"` without the extra; this additive change to the tool's JSON response is the one behaviour difference without the extra and is listed in the CHANGELOG (FR-019). No new MCP tool; the registered set stays the nine of 0.3/0.4.
- **FR-009 (needs wiki-studio ≥ 0.2)**: A contract test MUST assert that `EXPORT_MAP`, `IMPORT_MAP` and `PAGE_SECTIONS` in `wiki/sync.py` agree with `wiki_studio.schema` (page type → directory, required H2 sections, valid page types) so the duplicated schema cannot drift; the same task raises the **dev** dependency pin to `>=0.2,<1` and updates `poetry.lock`, so the module is always present where the dev group is installed. The test MUST FAIL, not skip, when `wiki_studio.schema` cannot be imported, unless the environment variable `MK_TEST_NO_EXTRA=1` marks a deliberate no-extra run (the name is deliberately outside the `MEMKERNEL_` prefix: `MemKernelSettings` warns about unknown prefixed keys and `test_config.py` asserts no such warning); an unexpected import error therefore turns CI red. memkernel keeps its own constants so the bridge works without the extra. Until 0.2, FR-003's lint contract test is the only drift guard.
- **FR-010 (companion, wiki-studio 0.2.0, not built here)**: wiki-studio MUST expose `api.propose(edits: list[PageEdit], paths, *, name) -> Path` writing a patch-set directory (documented on-disk format, `WikiPatchSet` and `PageEdit` declared public), a `wiki_studio.schema` module (`PAGE_TYPES: dict[str, PageTypeSpec(directory, required_sections)]`, `VALID_PAGE_TYPES`, `REQUIRED_KEYS`), and fix `docs/consumers.md` (`memkernel wiki_export` is an MCP tool, not a shell command). Tracked as a wiki-studio issue opened from this spec.

### Track B — evidence (issue #17), amended 2026-10-16 (option B)

- **FR-011 (runner scope)**: `eval/lifecycle-suite/runner.py` MUST orchestrate only the four lifecycle groups of FR-013: create a run, chain its sessions, apply each arm's persistence rule between sessions (FR-012), switch namespace where a task requires it, run each session as `claude -p <prompt> --output-format stream-json` in a fresh process, invoke the task's checker, and write records (FR-018). It MUST NOT run the `agent-memory-bench` retrieval grid, implement a statistics engine beyond the per-cell counts and paired differences FR-017 names, or grow general benchmark features (no plugin registry, no arm discovery, no grid of conditions). It is stdlib-only and runs on Python 3.11 like the rest of `eval/`; nothing in it imports `agent-memory-bench`.
- **FR-012 (arms and frozen persistence rules)**: Six arms: `bare` (no instruction, nothing persists), `placebo` (length-matched neutral prose, nothing persists), `protocol` (memkernel's CLAUDE.md block with no server behind it, nothing persists), `claude_md` (the agent may write files into its workspace; those files persist), `fs_grep` (the rendered transcript of every earlier session of the chain persists in a grep directory, with a one-line instruction naming it), `memkernel` (the MCP server and the three lifecycle hooks from `templates/` at the code-freeze SHA, the CLAUDE.md block; the store under the chain's namespace persists). Every arm receives the same task prompt and the same governing information in the same session and the same opportunity to save it (the prompt states that later sessions may need what was learned); only the persistence rule differs. Each arm's rule, instruction bytes and allowed tools are frozen in `eval/lifecycle-suite/arms/<arm>/config.frozen.json`, and a unit test asserts the runner carries exactly what the rule permits and nothing else. Per run: a fresh workspace restored from the task fixture, a fresh `HOME` and `CLAUDE_CONFIG_DIR` under the run root, Claude Code's own auto-memory and history empty, no user-level instructions.
- **FR-013 (tasks)**: `eval/lifecycle-suite/tasks/<id>/` and `oracles/<id>/` MUST follow `agent-memory-bench`'s task format (specification, fixture tree, checker, naive reference that MUST fail, informed reference that MUST pass, oracle inputs absent from the sandbox), five to eight tasks per group: `lc-retain` (fact met in session *n*, graded in session *n+1*; a revised-fact variant has the fact replaced in session *n+1* and grades session *n+2* on the current fact), `lc-reval` (the fixture changes between sessions; a stale informed reference MUST fail), `lc-wiki` (knowledge exported in one namespace with `wiki_export`, imported in a second with `wiki_import`, used there; non-memkernel arms get the wiki directory through their own persistence rule only), `lc-compact` (within one session; the fact is established before compaction and needed after it). CI MUST assert every naive reference fails and every informed reference passes with no model call (harness-free, Python 3.11).
- **FR-014 (credential-free demonstration)**: `runner.py --demo` MUST replay scripted sessions through a stub agent, with no model call, and show: state carried across sessions for each arm exactly as frozen, a namespace switch, and the runner's handling of compaction and `PreCompact`/`PostCompact` hook events using **simulated** events. A test runs it in CI. It does not claim that Claude Code compacts; that proof belongs to calibration (FR-015).
- **FR-015 (calibration)**: Before any measured session, a short calibration run on the chosen Claude model through the real runner MUST: prove on a live session that Claude Code compacts and that the arm's `PreCompact` and `PostCompact` hooks run and are recorded (if no live compaction can be produced, `lc-compact` is dropped and the report says so); measure per-session token usage per arm (input, cache write, cache read, output) for the budget; and surface wiring failures. Calibration uses tasks outside the measured set or is discarded wholesale; its configuration, cost and exclusion reasons are reported, its outcomes never enter the measured results. Tasks, arm configurations and the preregistration are frozen after calibration.
- **FR-016 (preregistration)**: `eval/lifecycle-suite/preregistration.md` MUST be committed before the first measured session and name: the code-freeze SHA, the Claude model and provider, arms, task set, runs per arm per task, the budget derived from calibration at explicit prices, the primary endpoint (paired task success per task × run of `memkernel` against `claude_md` and `fs_grep`, the files-carry-state controls), secondary comparisons against `bare`, `placebo` and `protocol`, the threshold and no-gain band, the minimum sample for an inferential claim, and the descriptive label when below it. Before the first measured session the preregistration commit MUST be pushed and its SHA and the file's sha256 posted on issue #17; that comment's timestamp is the external evidence of when it existed (commit dates are a secondary check). Deviations are disclosed in the report.
- **FR-017 (measured run, freeze and report)**: The measured run MUST execute on a **code-freeze SHA** of `main` (after US2 and US3 merged, version string `0.5.0rc1`). The next commit, the **preregistration commit**, adds only `eval/lifecycle-suite/preregistration.md`; its SHA is recorded as `eval/lifecycle-suite/PREREG_COMMIT`. Between the code-freeze SHA and the `v0.5.0` tag, `eval/check_freeze.py <code-freeze-sha>` (stdlib-only, reading `PREREG_COMMIT` itself) MUST pass: `git diff --name-only <code-freeze-sha> HEAD` is a subset of {`CHANGELOG.md`, `README.md`, `pyproject.toml`, `src/memkernel/__init__.py`, `eval/lifecycle-suite/preregistration.md`, `eval/lifecycle-suite/PREREG_COMMIT`, `eval/lifecycle-suite/results/**`, `eval/lifecycle-suite/report-0.5.0.md`}; the two version files differ only on their version line; and the commit `PREREG_COMMIT` names is a descendant of the code-freeze SHA and an ancestor of HEAD, differs from the freeze by exactly `eval/lifecycle-suite/preregistration.md`, equals the first entry of `git rev-list --reverse --ancestry-path <code-freeze-sha>..HEAD -- eval/lifecycle-suite/preregistration.md`, and has the same blob of that file as HEAD. `docs/roadmap.md` is not on the allowlist: roadmap ticks land after the tag. `eval/lifecycle-suite/report-0.5.0.md` MUST be derived by the runner's report step from the committed records, be titled and labelled **maintainer-run supplemental evaluation** (memkernel's own runner, not a third-party harness), name the code-freeze SHA, the preregistration commit and the tag, report every arm and group including failures, nulls and discarded runs, give calibration's configuration, cost and exclusions separately, carry the descriptive-or-inferential label, and be linked from the README evidence line and the 0.5.0 release notes. Upstream retrieval results, if any exist, are never merged into it.
- **FR-018 (records, diagnostics, data handling)**: Raw streams stay under the run root outside any git checkout. Published records are receipts: per session the arm, task, run, success, counts of tool calls by tool name, token usage, wall time, and sha256 of the prompt, response and tool payloads, never their content. Diagnostics, computed from the raw streams before publication and published as counts only, are: re-reads after resume, calls before the first `retain`, recall-to-use (`ref_id`s returned by `recall` that a later `get` or `ask` names / returned), and compaction and hook events observed. `eval/lifecycle-suite/scan_secrets.py` (stdlib-only, tested on a fixture with planted secrets) MUST pass over the results directory, and the operator reviews it before commit.
- **FR-019**: `pyproject.toml` and `memkernel.__version__` MUST be `0.4.1` after US1 (released 2026-10-15: docs, the wiki-studio contract test, and the #15 `.env` fix that was waiting under Unreleased) and `0.5.0` after US4; `CHANGELOG.md` gains the `[0.5.0]` section (the extra, ADR-010, the `wiki_export` report, and as far as wiki-studio 0.2 allows the gate and `MEMKERNEL_WIKI_PROPOSALS_DIR`; the lifecycle suite and the report). Every new behaviour has unit tests; coverage stays ≥ 80 percent; `core/ports.py` stays excluded.
- **FR-020 (upstream retrieval arm, not a release gate)**: The integration questions are put to `agent-memory-bench` first. Only after its maintainers confirm the intended path is an adapter contributed upstream; it then follows these rules: it ingests the harness's neutral rendering of each transcript, byte-identical across arms, through `retain(type="document")` and nothing else (no labelled facts, dates or supersession metadata); the document-store mode (`document_store: local`, chunking, summary and embedding settings) is declared in its frozen configuration; write tools are withheld in the grid, so the grid measures read-only retrieval over a pre-ingested corpus and does not exercise `retain`, supersession, revalidation or the hooks, which any report of it MUST state. Its results are reported separately from FR-017's report. If upstream does not answer before 0.5.0, 0.5.0 ships without it.

## Constraints / What NOT to Build

- No `wiki query` or `wiki ingest` tool, no backend-less query API use, no
  subprocess to `claude`, `codex`, `cursor` or `pi` from inside the server.
- No tenth MCP tool; lint feedback rides on `wiki_export`.
- No required runtime dependency; the extra is optional and lazily imported.
- No runtime derivation of the schema from wiki-studio: constants stay in
  memkernel, equality is tested.
- No retrieval-grid runner, no judge, no statistics engine of our own (the
  "no runner" constraint of 2026-10-15, narrowed to the grid on 2026-10-16):
  the lifecycle runner orchestrates the four lifecycle groups only (FR-011).
- No LLM judge, rubric or partial credit; the only endpoint is executable
  task success; diagnostics are counts over tool-call records.
- No paid run in CI: CI runs the reference-solution assertions, the
  credential-free demonstration, the persistence-rule test, the diagnostics
  and secret-scan fixture tests and the freeze-verifier test only. No
  measured run without a committed, announced preregistration; no
  calibration outcome in the results; no inferential wording below the
  predeclared sample; no raw transcript in the repository.
- No per-task tuning of an arm's configuration or instruction after
  calibration.
- No merging of upstream retrieval results into the lifecycle report.
- No token-savings claim anywhere; cost is reported, not promised.
- Nothing in `core/` changes.
- wiki-studio-side work (FR-010) is specified, not built, in this repo.

## Key Entities

- **ADR-010** — decision record for the optional wiki-studio extra.
- **LintSummary** — pydantic model in `wiki/sync.py`, wiki-studio lint and health findings on an export.
- **Lifecycle runner** — `eval/lifecycle-suite/runner.py`, stdlib-only, four groups only (FR-011).
- **Arm configuration** — `eval/lifecycle-suite/arms/<arm>/config.frozen.json`: persistence rule, instruction bytes, allowed tools (FR-012).
- **Lifecycle tasks** — `eval/lifecycle-suite/tasks/<id>/` and `oracles/<id>/` in `agent-memory-bench`'s task format, four groups (`lc-retain`, `lc-reval`, `lc-wiki`, `lc-compact`).
- **Calibration record** — configuration, cost and exclusions of the calibration run, reported, never scored (FR-015).
- **Preregistration** — `eval/lifecycle-suite/preregistration.md`, committed, pushed and announced on #17 before the first measured session.
- **Freeze verifier** — `eval/check_freeze.py`, allowlist, version-line-only check, preregistration lock on the commit `PREREG_COMMIT` names.
- **Report** — `eval/lifecycle-suite/report-0.5.0.md`, the maintainer-run supplemental evaluation.
- **Upstream adapter** — `adapters/memkernel/` in `agent-memory-bench`, after its maintainers confirm the path (FR-020, not a release gate).
- **PageEdit / WikiPatchSet / propose()** — wiki-studio 0.2 public contract memkernel exports through.

## Success Criteria

- SC-1: `pip install memkernel` pulls no new dependency; `pip install "memkernel[wiki]"` pulls wiki-studio only.
- SC-2: With the extra, an export whose draft would violate the schema leaves the wiki unchanged and the tool reports the violation; without the extra, the files `wiki_export` writes (pages, `index.md`, `log.md`) are byte-identical to 0.4's, and the only response change is the additive `lint` and `lint_hint` keys (FR-008), recorded in the CHANGELOG.
- SC-3: The schema contract test fails when either `PAGE_SECTIONS` or wiki-studio's `PAGE_TYPES` changes alone.
- SC-4: Every lifecycle task's naive reference fails and informed reference passes in CI with no model call; `runner.py --demo` shows each arm's frozen carry-over, a namespace switch and simulated compaction and hook events, in CI.
- SC-5: The GitHub timestamp of the issue #17 comment that names the preregistration commit and its sha256 precedes the first measured session's timestamp in the results; the sha256 in that comment equals the blob at the commit `PREREG_COMMIT` names; the commit's author date is consistent with that order (secondary check).
- SC-6: `report-0.5.0.md` is labelled a maintainer-run supplemental evaluation, reports every arm and lifecycle group with failures, nulls and discarded runs, gives calibration's configuration, cost and exclusions separately, states whether a live compaction was proven, and carries the descriptive-or-inferential label.
- SC-7: Nine MCP tools; fast suite green; coverage ≥ 80 percent; ruff and mypy clean; `ci.yml` unchanged unless FR-004's one condition applies.
- SC-8: `check_freeze.py` rejects any file outside the allowlist, any non-version change to the two version files, and any change to `preregistration.md` after the preregistration commit; the secret scan rejects the planted-secret fixture. The persistence-rule test fails if the runner carries anything an arm's frozen rule does not permit.

---
feature_id: memkernel-0-5
status: draft
date: 2026-10-15
---

# Spec: memkernel 0.5 — evidence and wiki-studio

Two tracks. Track A makes wiki-studio the owner of the wiki schema, the
lint and health pass and the promote gate, behind an optional extra. Track B
answers issue #17 by entering memkernel into the public, preregistered,
execution-graded `agent-memory-bench` (GiulioDER/agent-memory-bench,
Apache-2.0) through a reviewable adapter, and by adding only the lifecycle
scenarios that benchmark does not measure, as executable tasks for the same
harness. No LLM judge anywhere. US1 ships as 0.4.1 (docs only); US2–US4 ship
as 0.5.0.

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

### US3: memkernel is a measurable arm of a public benchmark (Priority: HIGH, release 0.5.0)

A maintainer or contributor runs `agent-memory-bench` at a pinned commit
with a `memkernel` adapter and frozen configuration next to the harness's
own control arms (`bare`, `claude_md`, `placebo`, `protocol`, `fs_grep`).
Every number comes from the harness's execution-graded checkers and cost
ledger; the adapter and configuration are reviewable before any run.

### US4: The lifecycle claims have executable evidence too (Priority: HIGH, release 0.5.0)

The public benchmark ranks retrieval over a corpus ingested before the run.
memkernel's claims that the benchmark does not test — retention written in
one session and used in the next, recovery after compaction, revalidation
after the repository changed, knowledge shared through the wiki bridge —
become a small supplemental suite of tasks in the benchmark's own format
(fixture, checker, naive and informed references) and are run with the same
harness and arms. A first preregistered run of both is published with 0.5.0,
null results included.

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

### Track B — evidence (issue #17)

- **FR-011**: `eval/agent-memory-bench/` MUST hold a memkernel adapter for `agent-memory-bench` in the layout its `adapters/<name>/` contract requires (adapter module implementing `harness.adapters.base.MemoryAdapter`, `config.frozen.json`, `versions.lock` pinning memkernel and every dependency, `instruction_appendix.md` with its published size, the filled vendor-review template), plus `BENCHMARK_COMMIT` pinning the benchmark repository SHA the adapter was written against. The adapter MUST enter through memkernel's published Claude Code integration only (the `memkernel` MCP server from `templates/`, the CLAUDE.md block, the lifecycle hooks); it MUST NOT reach into memkernel internals. The same directory MUST be submitted upstream as a pull request to the benchmark repository; the in-repo copy is the mirror that 0.5.0 freezes.
- **FR-012**: The adapter's ingest path MUST feed exactly the benchmark's verbatim transcript bytes, and nothing else, through the published write path: one `retain(type="document", source=<transcript name>)` per transcript over the MCP server. No benchmark-labelled facts, no dates, no `supersedes` links and no corpus metadata of any kind reach the store: extraction, supersession and conflict handling are part of what the benchmark measures, and every arm must receive the same bytes. Tenant isolation maps to `MEMKERNEL_PROJECT_ID` per namespace. The server built by `build_service()` always wires the local document store, so each transcript body is stored and chunk-indexed and the memkernel record keeps a summary (`core/services.py`, `_retain_document`); `config.frozen.json` MUST record this mode explicitly (`document_store: local`, `chunk_size`, `chunk_overlap`, `document_summary_chars`, `embedding_model`, `ask_top_k`) so the retrieval behaviour under measurement is declared, not implied. The mapping MUST NOT be tuned per task. Explicit `supersedes` is exercised only in the lifecycle suite (FR-015, `lc-retain` revised-fact tasks), where the agent itself writes it.
- **FR-013**: Control arms are the harness's own: `bare` (floor), `claude_md` (baseline), `placebo`, `protocol` and `fs_grep` (files already carry the state: the negative control issue #17 asks for). memkernel adds no control arm of its own. The run MUST be paired by task, seed and fixture and admitted by the harness's admission gate; discarded cells are reported, never dropped silently.
- **FR-014**: `eval/agent-memory-bench/preregistration.md` MUST be committed, and its sha256 recorded, before the first measured session: benchmark commit, memkernel RC SHA, model and provider (a Claude model, since the claim is about Claude Code; the benchmark's official grid used another vendor and is not comparable), arms, task set (the official grid plus the `xs-*` cross-session tasks and the supplemental suite of FR-015), seeds per cell, explicit prices, the primary endpoint (paired task success against `claude_md`), the predeclared threshold and no-gain band, the minimum sample for an inferential claim, and the statement that the run is descriptive when below it. Before the first measured session, the preregistration commit MUST be pushed to `origin` and its SHA and the file's sha256 posted as a comment on issue #17; that comment's GitHub timestamp is the external evidence of when the preregistration existed (commit dates can be set freely and count only as a secondary check). Deviations are disclosed in the report, following the benchmark's own practice.
- **FR-015**: `eval/lifecycle-suite/` MUST contain executable tasks in the benchmark's task format (`tasks/<id>/` specification, fixture, checker, naive reference asserted to fail and informed reference asserted to pass, `oracles/<id>/` absent from the sandbox) for the four claims the public grid does not measure. **Exposure rule**: in every lifecycle task, every arm encounters the governing fact in the same first session, delivered inside that session's task (its prompt, repository or command output), never through the pre-run corpus feed; arms differ only in what their published integration persists into the next session (memkernel: hooks and `retain`; `fs_grep`: the harness writes the first session's transcript to its grep directory; `claude_md`: whatever the agent wrote into files; `bare` and `placebo`: nothing). For `lc-compact`, which runs within one session, the same rule reads: every arm meets the fact before the compaction in the same session, and arms differ only in what their integration carries across the compaction (memkernel: the `PreCompact`/`PostCompact` hooks and the store; the others: whatever Claude Code's own compaction summary keeps). Groups: `lc-retain-*` (fact met in session *n*, artifact graded in session *n+1*; a revised-fact variant has the agent replace the fact in session *n+1* and grades session *n+2* on the current fact, which is where memkernel's explicit `supersedes` is measured), `lc-compact-*` (session *n* long enough to trigger compaction before the fact is needed again within the same session; the checker requires the pre-compaction fact), `lc-reval-*` (the repository changes between sessions; the stale informed reference MUST fail and the checker rewards the current state: revalidation's `needs_review` path), `lc-wiki-*` (knowledge exported with `wiki_export` in one namespace, imported with `wiki_import` in a second, used there). Five to eight tasks per group. CI MUST assert every naive reference fails and every informed reference passes against the checker with no model call. **Conditional scope**: every group depends on a harness capability that task 11 validates on the pinned commit, one mechanism per group: `lc-retain` needs each arm's first-session state carried into the next session (cross-session carry-over); `lc-reval` needs the same carry-over plus a repository mutation between the two sessions; `lc-wiki` needs the workspace filesystem (the wiki directory) carried into a second session that runs under a second namespace; `lc-compact` is within-session and needs a session long enough to trigger Claude Code compaction with the arm's `PreCompact`/`PostCompact` hooks running inside the executor. A group whose mechanism the harness lacks is contributed upstream as a harness extension first and left out of 0.5.0, stated in the preregistration and the report; nothing in this suite is unconditional. The suite is submitted upstream as well.
- **FR-016**: Secondary, trace-derived diagnostics (never endpoints) MUST be computed by `eval/lifecycle-suite/diagnostics.py` (stdlib-only) from the harness's published streams and cost ledger: re-reads after resume (|`Read` tool calls in session *n+1* on paths already read in session *n*| / |`Read` calls in *n+1*|), tokens and wall time per arm, calls before the first `retain`, and recall-to-use (|`ref_id`s returned by `recall` that a later `get` or `ask` call in the same session names| / |`ref_id`s returned|). No judge, no annotation; every quantity is a count over tool-call records. A unit test runs it over a checked-in fixture stream.
- **FR-017**: Data handling MUST follow the benchmark's `docs/DATA_SAFETY.md`: live runs declare provider retention, and only what the harness publishes (session logs, streams, admission verdicts, costs, hashed receipts) is committed under `eval/agent-memory-bench/results/<run_id>/`; nothing beyond the harness's own output format is added, and a credential-pattern scan (`eval/lifecycle-suite/scan_secrets.py`, stdlib-only, tested against a fixture with planted secrets) MUST pass over the results directory before commit.
- **FR-018**: The run MUST execute on a **code-freeze SHA** of `main` (after US2 and US3 merged, version string `0.5.0rc1`). The next commit, the **preregistration commit**, adds only `eval/agent-memory-bench/preregistration.md`, which names the code-freeze SHA; its SHA is recorded as `eval/agent-memory-bench/PREREG_COMMIT`. Between the code-freeze SHA and the `v0.5.0` tag, `eval/check_freeze.py <code-freeze-sha>` (stdlib-only, reading `PREREG_COMMIT` itself) MUST pass: `git diff --name-only <code-freeze-sha> HEAD` is a subset of the allowlist {`CHANGELOG.md`, `README.md`, `pyproject.toml`, `src/memkernel/__init__.py`, `eval/agent-memory-bench/preregistration.md`, `eval/agent-memory-bench/PREREG_COMMIT`, `eval/agent-memory-bench/results/**`, `eval/agent-memory-bench/report-0.5.0.md`}; the diffs of `pyproject.toml` and `src/memkernel/__init__.py` touch only their version line (`version = "..."` and `__version__ = "..."`); and the preregistration is locked against the commit `PREREG_COMMIT` names: that commit MUST be a descendant of the code-freeze SHA and an ancestor of HEAD, its diff against the code-freeze SHA MUST be exactly `eval/agent-memory-bench/preregistration.md`, it MUST equal the first entry of `git rev-list --reverse --ancestry-path <code-freeze-sha>..HEAD -- eval/agent-memory-bench/preregistration.md`, and the blob of `preregistration.md` at HEAD MUST equal its blob at that commit. Moving `PREREG_COMMIT` to a later commit therefore fails the check. Any other change invalidates the run. `docs/roadmap.md` is not on the allowlist: roadmap ticks land in a commit after the tag. `eval/agent-memory-bench/report-0.5.0.md` MUST be derived from the harness's statistics output, name the benchmark commit, the code-freeze SHA, the preregistration commit and the final tag, report every arm and condition including nulls and discarded cells, carry the descriptive-or-inferential label from FR-014, and be linked from the README evidence line and the 0.5.0 release notes.
- **FR-019**: `pyproject.toml` and `memkernel.__version__` MUST be `0.4.1` after US1 and `0.5.0` after US4; `CHANGELOG.md` MUST gain both sections (0.4.1: docs and contract test only; 0.5.0: the extra, ADR-010, `wiki_export` report and gate, `MEMKERNEL_WIKI_PROPOSALS_DIR`, the benchmark adapter, the lifecycle suite and the report). Every new behaviour has unit tests; coverage stays ≥ 80 percent; `core/ports.py` stays excluded.

## Constraints / What NOT to Build

- No `wiki query` or `wiki ingest` tool, no backend-less query API use, no
  subprocess to `claude`, `codex`, `cursor` or `pi` from inside the server.
- No tenth MCP tool; lint feedback rides on `wiki_export`.
- No required runtime dependency; the extra is optional and lazily imported.
- No runtime derivation of the schema from wiki-studio: constants stay in
  memkernel, equality is tested.
- No benchmark runner, judge, event schema or statistics code of our own:
  the harness is `agent-memory-bench` at a pinned commit; if it cannot run a
  task of the supplemental suite, the task is fixed or dropped, not the
  harness replaced.
- No LLM judge, rubric or partial credit; the only endpoint is executable
  task success; diagnostics are counts over tool-call records.
- No benchmark in CI beyond the reference-solution assertions and the
  diagnostics fixture test; no run without a committed preregistration; no
  inferential wording below the predeclared sample; no raw transcript in the
  repository beyond what the harness itself publishes.
- No per-task tuning of the adapter or the instruction appendix.
- No token-savings claim anywhere; cost is reported, not promised.
- Nothing in `core/` changes.
- wiki-studio-side work (FR-010) is specified, not built, in this repo.

## Key Entities

- **ADR-010** — decision record for the optional wiki-studio extra.
- **LintSummary** — pydantic model in `wiki/sync.py`, wiki-studio lint and health findings on an export.
- **memkernel adapter** — `eval/agent-memory-bench/` mirror of `adapters/memkernel/` upstream: adapter module, `config.frozen.json`, `versions.lock`, `instruction_appendix.md`, vendor review, `BENCHMARK_COMMIT`.
- **Preregistration** — `eval/agent-memory-bench/preregistration.md`, committed and hashed before the first measured session.
- **Lifecycle suite** — `eval/lifecycle-suite/tasks/<id>/` and `oracles/<id>/` in the benchmark's task format, four groups (`lc-retain`, `lc-compact`, `lc-reval`, `lc-wiki`).
- **Freeze verifier** — `eval/check_freeze.py`, allowlist, version-line-only check, preregistration lock on the commit `PREREG_COMMIT` names (descendant, exact diff, first toucher, equal blob).
- **Report** — `eval/agent-memory-bench/report-0.5.0.md`, derived from the harness statistics.
- **PageEdit / WikiPatchSet / propose()** — wiki-studio 0.2 public contract memkernel exports through.

## Success Criteria

- SC-1: `pip install memkernel` pulls no new dependency; `pip install "memkernel[wiki]"` pulls wiki-studio only.
- SC-2: With the extra, an export whose draft would violate the schema leaves the wiki unchanged and the tool reports the violation; without the extra, the files `wiki_export` writes (pages, `index.md`, `log.md`) are byte-identical to 0.4's, and the only response change is the additive `lint` and `lint_hint` keys (FR-008), recorded in the CHANGELOG.
- SC-3: The schema contract test fails when either `PAGE_SECTIONS` or wiki-studio's `PAGE_TYPES` changes alone.
- SC-4: The harness's dry run resolves the `memkernel` arm with no credentials; every lifecycle task's naive reference fails and informed reference passes in CI with no model call.
- SC-5: The GitHub timestamp of the issue #17 comment that names the preregistration commit and its sha256 precedes the first measured session's timestamp in the results; the sha256 in that comment equals the blob at the commit `PREREG_COMMIT` names; the commit's author date is consistent with that order (secondary check).
- SC-6: `report-0.5.0.md` reports every arm and condition of the official grid, the `xs-*` tasks and the four lifecycle groups, with intervals, discarded cells and nulls, and carries the descriptive-or-inferential label.
- SC-7: Nine MCP tools; fast suite green; coverage ≥ 80 percent; ruff and mypy clean; `ci.yml` unchanged unless FR-004's one condition applies.
- SC-8: `check_freeze.py` rejects any file outside the allowlist, any non-version change to the two version files, and any change to `preregistration.md` after the preregistration commit; the secret scan rejects the planted-secret fixture.

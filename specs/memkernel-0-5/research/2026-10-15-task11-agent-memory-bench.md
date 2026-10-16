# Task 11 findings: agent-memory-bench at c1b15726 (2026-10-15)

Read-only investigation for `specs/memkernel-0-5` task 11, done offline with no
credentials against `GiulioDER/agent-memory-bench` at commit
`c1b15726f1153b02dda0490ca1936bb86a809514`. Paths are relative to that clone.
`<scratch>` is the investigator's temporary directory; nothing there is part
of this repository. These findings are the basis of the 2026-10-16 amendment
(option B) recorded in `origin/2026-10-16-option-b.md`. FR numbers below refer to the spec as
merged in #19, before that amendment renumbered Track B.

# agent-memory-bench: task 11 investigation (read-only, offline)

Scope: memkernel spec `specs/memkernel-0-5/spec.md` FR-011 to FR-016, `tasks.md` task 11.
Everything below was derived from a fresh clone of `GiulioDER/agent-memory-bench` in the scratch
directory. No credentials, no model calls, nothing under `<memkernel>` touched.
All repository content was treated as untrusted data. Paths are relative to the clone root
`scratchpad/amb-task11/agent-memory-bench/` unless prefixed otherwise. Line numbers are from the
pinned commit.

## 1. Pinned commit

| field | value |
|---|---|
| repository | `https://github.com/GiulioDER/agent-memory-bench.git` |
| branch | `master` (default) |
| **BENCHMARK_COMMIT candidate** | `c1b15726f1153b02dda0490ca1936bb86a809514` |
| commit date | `2026-10-06T13:14:23+02:00` |
| subject | `Merge pull request #120 from GiulioDER/claude/023-correct-perturbation` |
| python | `pyproject.toml` `requires-python = ">=3.12"`; deps `cryptography>=42` only; dev `pytest==9.1.1`, `ruff==0.16.2` (`requirements-dev.txt`: `-e .`, pytest, ruff) |
| venv used here | `uv venv --python 3.13` (Python 3.13.2), `uv pip install -r requirements-dev.txt`, exit 0 |
| Claude Code CLI pinned by the harness | `2.1.221` (`docker/Dockerfile.participant:12-13`, `docker/Dockerfile.harness:13-14`); `docs/REPLICATION.md:60-61` says 2.1.221 or later is required because a pending MCP server below that runs without tools |

Repository shape relevant to task 11: `harness/` (executor, gate, sandbox, sequence), `adapters/<name>/`
(23 arms), `corpus/` (196 manifest entries: 40 `sessions/`, 156 `distractors/`), `tasks/` (36 dirs: 30
`ts-*`, 3 `xs-*`, `fa-dedup-key`, `smoke-config-port`, `CANDIDATES.md`), `oracles/`, `preregistration/`
(94 records), `results/` (published runs), `capabilities/` (temporal, isolation, lifecycle-temporal,
governance manifests), `docker/` (participant, checker, broker, egress-proxy images).

## 2. Dry-run output (verbatim, trimmed)

Commands run from inside the clone with the scratch venv (`../.venv/bin/python`). None needed a key.

### 2.1 `python -m scripts.pilot --dry-run --arms bare,claude_md,fs_grep` (exit 0)

```
[dry-run] run-id pilot-001, model deepseek/deepseek-v4-flash, seeds [0, 1, 2]
[dry-run] arms   ['bare', 'claude_md', 'fs_grep']
[dry-run] instruction variant 'oneliner', neutral=False
[dry-run] structured decisions False
[dry-run]   bare       instruction     0 bytes
[dry-run]   claude_md  instruction     0 bytes
[dry-run]   fs_grep    instruction  4021 bytes
[dry-run] tasks  30: ts-append-only, ts-atomic-write, ts-base36-id, ts-bom-merge, ts-bool-env, ts-casefold-sort, ts-cli-exitcode, ts-config-layer, ts-crlf-export, ts-csv-quote, ts-dedup-order, ts-empty-input, ts-glob-hidden, ts-golden-regen, ts-idempotent-run, ts-ignore-gen, ts-json-sorted, ts-legacy-hash, ts-log-mask, ts-manifest-rel, ts-mig-name, ts-natural-order, ts-nfc-count, ts-quote-shell, ts-retry-cap, ts-round-money, ts-schema-additive, ts-semver-pin, ts-stable-sort, ts-tz-utc
[dry-run] work root <tmp>
[dry-run] would run 270 session(s); nothing written, nothing executed
```

270 = 30 tasks x 3 seeds x 3 arms (`scripts/pilot.py:1653-1657`). The dry run prints tasks, seeds and
arms, and the session count; it does not print a cell count, but cells = tasks x seeds (see section 8).

### 2.2 `python -m scripts.pilot --dry-run --arms bare,claude_md,placebo,protocol,fs_grep` (exit 1)

```
the `protocol` arm is the instruction-only control for the shared memory protocol, so it is only meaningful with --memory-instruction in ('protocol', 'draft'). With `skill` or `oneliner` it would carry a different instruction from the memory arms it exists to be compared against.
```

The default `--memory-instruction` is `oneliner`; the `protocol` arm refuses it. Rerun with the fair
variant (`--memory-instruction protocol`, which preregistration 026 / official-003 used):

```
[dry-run] run-id pilot-001, model deepseek/deepseek-v4-flash, seeds [0, 1, 2]
[dry-run] arms   ['bare', 'claude_md', 'placebo', 'protocol', 'fs_grep']
[dry-run] instruction variant 'protocol', neutral=False
[dry-run] structured decisions False
[dry-run]   bare       instruction     0 bytes
[dry-run]   claude_md  instruction     0 bytes
[dry-run]   placebo    instruction     0 bytes
[dry-run]   protocol   instruction  3610 bytes
[dry-run]   fs_grep    instruction  4021 bytes
[dry-run] tasks  30: ts-append-only, ... ts-tz-utc   (same 30 as above)
[dry-run] would run 450 session(s); nothing written, nothing executed
```

### 2.3 Other probes

| command (abridged) | result |
|---|---|
| `--arms bare,claude_md,placebo,protocol,fs_grep --memory-instruction protocol --seeds 1 --tasks ts-tz-utc,xs-evolve-lease,xs-join-batch,xs-widen-manifest --include-synthesis` | `tasks 4: ts-tz-utc, xs-evolve-lease, xs-join-batch, xs-widen-manifest` / `would run 20 session(s)` (exit 0) |
| `--arms bare,claude_md --tasks xs-evolve-lease` (no `--include-synthesis`) | `unknown task(s) ['xs-evolve-lease']; a silent subset is a different run` |
| `--arms bare,claude_md,recall --memory-instruction protocol --seeds 1` (no `RECALL_DSN`) | resolves: `recall instruction 4207 bytes`, `would run 90 session(s)`; a dry run does not need the DSN (`scripts/pilot.py:1533-1535`) |
| `--arms bare,memkernel` | `unknown arms ['memkernel']; choose from ('bare', 'placebo', 'claude_md', 'protocol', 'fs_grep', 'recall', ... 'claude_mem', 'aml_c6_prefetch', 'aml_c7_prefetch')` — the registry is the `ARMS` tuple at `scripts/pilot.py:176-184` plus `adapter_for` at `:790` |
| `--arms bare,claude_md --seeds 1 --condition superseded` | still 30 tasks, 60 sessions: `pilot.py` does not filter tasks by condition; `scripts/abstention.py` does (section 8) |
| `python -m scripts.pilot --help` | options: `--run-id`, `--model` (default `deepseek/deepseek-v4-flash`), `--base-url` (default `https://openrouter.ai/api`), `--seeds` (default 3), `--seed-values`, `--continue-existing`, `--finalize-existing`, `--timeout` (default 600.0), `--namespace`, `--sequence-plan`, `--heldout-manifest`, `--memory-instruction {oneliner,skill,quality,protocol,draft,quality_gate_paired,decision_protocol_paired,oracle_ceiling_paired,premutation_checkpoint_paired}`, `--neutral-protocol`, `--emit-decisions`, `--emit-decision-stages`, `--arms`, `--tasks`, `--include-synthesis`, `--corpus-root`, `--condition {,present,absent,superseded,contradictory,adjacent}`, `--work-root`, `--dry-run`, `--prepare-only`, `--price-in`, `--price-out`, `--price-as-of` (all three required for a live run), `--price-cache-read`, `--price-cache-creation` |

### 2.4 Official-grid driver: `python -m scripts.abstention --dry-run --run-id probe --arms bare,claude_md,placebo,protocol,fs_grep --memory-instruction protocol --conditions present,absent,superseded,contradictory,adjacent --seeds 1` (exit 0)

`scripts/abstention.py` is what `scripts/launch_official.sh:143-147` invokes; per condition it
assembles a condition corpus and then shells out to `scripts/pilot.py --corpus-root ... --condition ...`
(`scripts/abstention.py:11-19, 318-388`). Resolved on this commit:

```
[present] 27 task(s), 196 session file(s) in the feed
[dry-run] tasks  27: fa-dedup-key, ts-atomic-write, ts-base36-id, ts-bom-merge, ts-casefold-sort, ts-cli-exitcode, ts-config-layer, ts-crlf-export, ts-dedup-order, ts-empty-input, ts-golden-regen, ts-idempotent-run, ts-ignore-gen, ts-json-sorted, ts-legacy-hash, ts-log-mask, ts-manifest-rel, ts-mig-name, ts-natural-order, ts-nfc-count, ts-quote-shell, ts-retry-cap, ts-round-money, ts-schema-additive, ts-semver-pin, ts-stable-sort, ts-tz-utc
[dry-run] would run 135 session(s); nothing written, nothing executed
[absent] 11 task(s), 185 session file(s) in the feed
[dry-run] tasks  11: ts-base36-id, ts-bom-merge, ts-dedup-order, ts-golden-regen, ts-ignore-gen, ts-legacy-hash, ts-mig-name, ts-natural-order, ts-schema-additive, ts-semver-pin, ts-tz-utc
[dry-run] would run 55 session(s); nothing written, nothing executed
[superseded] 10 task(s), 206 session file(s) in the feed
[dry-run] tasks  10: ts-base36-id, ts-bom-merge, ts-golden-regen, ts-ignore-gen, ts-legacy-hash, ts-mig-name, ts-natural-order, ts-schema-additive, ts-semver-pin, ts-tz-utc
[dry-run] would run 50 session(s); nothing written, nothing executed
[contradictory] 10 task(s), 206 session file(s) in the feed
[dry-run] tasks  10: ts-bom-merge, ts-dedup-order, ts-golden-regen, ts-ignore-gen, ts-legacy-hash, ts-mig-name, ts-natural-order, ts-schema-additive, ts-semver-pin, ts-tz-utc
[dry-run] would run 50 session(s); nothing written, nothing executed
[adjacent] 11 task(s), 196 session file(s) in the feed
[dry-run] tasks  11: ts-base36-id, ts-bom-merge, ts-dedup-order, ts-golden-regen, ts-ignore-gen, ts-legacy-hash, ts-mig-name, ts-natural-order, ts-schema-additive, ts-semver-pin, ts-tz-utc
[dry-run] would run 55 session(s); nothing written, nothing executed
[dry-run] nothing was ingested, run or analysed
```

Each condition also printed four `[retired] <condition>: ts-append-only / ts-bool-env / ts-csv-quote /
ts-glob-hidden excluded (...)` lines. Side effect worth knowing: even in `--dry-run` this driver
**assembles** `corpus/conditions/<condition>/seed-1/` inside the checkout (`scripts/abstention.py:318-324`);
the path is gitignored (`.gitignore:53`), so `git status` stays clean. Full output saved at
`scratchpad/amb-task11/abstention-dryrun.txt`.

## 3. Adapter contract (question a)

### 3.1 `harness.adapters.base.MemoryAdapter` (`harness/adapters/base.py:306-388`)

| member | signature / meaning | line |
|---|---|---|
| `name: str` | arm name, unique in the registry | 310 |
| `supported_gatings: tuple[str, ...]` | which gatings `search` answers; empty = not scorable for retrieval | 315 |
| `search(self, namespace, query, *, gating="served", limit=10) -> RankedResult` | optional; raise when unsupported, do not return empty | 317-338 |
| **`ingest(self, corpus: CorpusManifest, namespace: str) -> IngestReport`** | abstract; "feed the corpus through the product's own write path into namespace" | 340-342 |
| **`build(self, session_dir: Path, namespace: str) -> ArmSpec`** | abstract; once per session, deterministic for (frozen config, namespace); `config_dir_digest` asserted stable | 344-350 |
| `build_for_task(self, session_dir, namespace, task_id, user_input) -> ArmSpec` | default delegates to `build`; the runner always calls this (`scripts/pilot.py:1919, 1934, 1960`) | 352-361 |
| `prepare_for_session(self, namespace) / cleanup_after_session(self, namespace)` | optional lifecycle hooks (no caller found in `scripts/pilot.py`) | 363-367 |
| **`admission_signal(self) -> AdmissionSignal`** | abstract | 369-371 |
| `snapshot(self, namespace) / restore(self, snapshot)` | optional store snapshot; raise when unsupported | 373-383 |
| `describe(self) -> dict` | frozen config and versions, redacted, published beside the numbers | 385-388 |

Optional lifecycle surface (separate protocol, `harness/lifecycle.py:146-154`):
`ingest_event(self, namespace: str, event: LifecycleEvent, content: bytes) -> LifecycleIngestReport`.
It is driven only by `run_lifecycle_ingest` (`:162-188`) for the `capabilities/lifecycle-temporal.json`
fixture, never by the grid (`docs/LIFECYCLE_CAPABILITY.md:3-6, 18-34`).

### 3.2 Data classes

- `CorpusManifest` (`base.py:84-141`): `root: Path`, `sessions: Mapping[str, str]` (corpus-relative
  transcript path -> sha256). `load(corpus_root)` reads `manifest.json` (`:96-101`); `build()` globs
  `CORPUS_GLOBS = ("sessions/**/*.jsonl", "distractors/*.jsonl", "synthetic/**/*.jsonl")` (`:220`);
  `verify()` re-hashes every file and refuses a mismatch (`:132-141`).
- `IngestReport` (`:144-178`): `arm`, `namespace`, `sessions_offered`, `items_stored`, `wall_time_ms`,
  `llm_input_tokens`, `llm_output_tokens`, `local_model` (name the local embedder so a zero token
  count is not read as free), `notes`.
- `ArmSpec` (`:181-200`): `arm`, `mcp_config` (path to an `--mcp-config` file), `append_system_prompt_file`,
  `memory_tool_prefix`, `extra_allowed_tools`, `extra_args`, `config_dir` (isolated `CLAUDE_CONFIG_DIR`),
  `config_dir_digest`, `env`, `bare: bool = True`, `metadata`.
- `AdmissionSignal` (`harness/gate.py:67-81`): `arm`, `mcp_tool_prefixes`, `required_hooks`,
  `sandbox_paths`, `prompt_sha256`, `forbidden_prefixes` (filled by `with_forbidden_prefixes`, `:84-132`,
  which refuses two arms claiming one prefix), `metadata`.
- Namespaces must match `^[A-Za-z0-9][A-Za-z0-9._-]*$` (`base.py:246-268`); join through
  `namespace_path` (`:271-279`) because the joined path is later `rmtree`d.

How the harness consumes an `ArmSpec` (`scripts/pilot.py:2345-2380`): `ClaudeExecConfig(model=args.model,
timeout_s=args.timeout, env={**env, **spec.env}, bare=spec.bare, config_dir=spec.config_dir,
mcp_config=spec.mcp_config, strict_mcp_config=bool(spec.mcp_config), allowed_tools=BASE_TOOLS +
spec.extra_allowed_tools, disallowed_tools=DENIED_TOOLS, extra_args=spec.extra_args,
append_system_prompt_file=spec.append_system_prompt_file, permission_mode="acceptEdits",
memory_tool_prefix=spec.memory_tool_prefix or "mcp__never__", memory_event_tools=spec.metadata["memory_event_tools"])`.
`BASE_TOOLS = ("Read","Grep","Glob","Bash","Write","Edit")`, `DENIED_TOOLS = ("Bash(docker:*)","Bash(docker-compose:*)")`
(`:269-270`). The CLI line is built at `harness/claude_exec.py:251-285`:
`claude [--bare] -p <prompt> --output-format stream-json --verbose [--json-schema ..] [--model M]
[--mcp-config F] [--strict-mcp-config] [--allowed-tools ..] [--disallowed-tools ..]
[--append-system-prompt-file F] [--permission-mode acceptEdits] [--add-dir ..] <extra_args>`.

### 3.3 Directory contract and registration

`adapters/<name>/` holds `adapter.py`, `config.frozen.json`, optional `instruction_appendix.md`
(capped at `APPENDIX_MAX_BYTES = 1200`, `harness/instructions.py:59, 161-171`), `versions.lock`
(format example `adapters/supermemory/versions.lock`: `package==ver`, `source=`, `commit=`, `node=`),
`VENDOR_REVIEW.md` from `adapters/VENDOR_REVIEW_TEMPLATE.md`. `docs/INTEGRATION-CONTRACT.md:91-97`:
implement `ingest`, `build`, `admission_signal`, `describe`; register in `scripts/pilot.py::adapter_for`
(`:790-830`) and the `ARMS` tuple (`:176-184`); memory arms also belong in `MEMORY_ARMS` (`:249-256`)
and, if the runner fills the store, `SELF_INGESTING_ARMS` (`:260-263`); the per-arm instruction text
table is built in `memory_instructions` (`:695-748`). A memkernel arm is unknown until all of these are
edited (dry-run 6 above).

### 3.4 How `recall` wires an MCP server (`adapters/recall/adapter.py`)

- `config.frozen.json:1-29`: `server_name: "recall"`, `command: "python"`, `args: ["-m","recall_mcp.server"]`,
  `embedder`, `trust_mode`, `tool_prefix: "mcp__recall__"`, `allowed_tools: [8 read-only tools]`,
  `package_pin: "recall-rag[fastembed,mcp,voyage]==0.13.0"`, `environment`, `transport: "host"`, and
  `*_env` names for every host-specific value (never the values; note at `:35`).
- `build()` (`:1127-1186`): writes `<session_dir>/recall.mcp.json` =
  `{"mcpServers": {server_name: {"command", "args", "env"}}}` (`:1149-1158`); env from `_server_env`
  (`:544-560`: `RECALL_DSN`, `RECALL_EMBEDDER`, `RECALL_TRUST_MODE`, `RECALL_TENANT = namespace`,
  `RECALL_ENV`, plus `extra_env`) because "the env block REPLACES the environment" (`:8-12`); returns
  `ArmSpec(bare=True, mcp_config=<path>, append_system_prompt_file=<prompt>, memory_tool_prefix=prefix,
  extra_allowed_tools=(prefix+tool ...), config_dir_digest=sha256(config bytes + prompt bytes),
  metadata={"tenant": namespace, "memory_event_tools": {prefix+"recall_search": "retrieve", ...},
  "prompt_sha256": ...})` (`:1163-1186`).
- `build_for_task()` (`:1188-1204`) writes the prompt per task into the session dir (the namespace-keyed
  cache served one task's README to every task on `diagnostic-001`).
- `admission_signal()` = `AdmissionSignal(arm, mcp_tool_prefixes=(tool_prefix,))` (`:1206-1209`).
- `describe()` publishes `config_sha256` and `package_pin` (`:1211-1217`).
- `ingest()` (`:769-858`): `corpus.verify()`, render every manifest path to a staging dir with
  `render_corpus` (`:788-794`), then `python -m recall.cli --tenant <namespace> index <staged>`
  (`:799-808`); refuses an exit 0 with zero rows (`:838-845`). Under `transport: host/ssh` it only
  verifies a pre-built remote generation (`:771-772`).

Tenant/namespace isolation for an MCP arm = one env var per server process (`RECALL_TENANT`),
which maps directly to FR-012's `MEMKERNEL_PROJECT_ID` per namespace.

### 3.5 Instruction appendix and CLAUDE.md

`--bare` disables `CLAUDE.md`, hooks, plugins and MCP auto-discovery (`harness/claude_exec.py:184-187`),
so nothing enters through a `CLAUDE.md` file. The "CLAUDE.md bundle" is the fixture README served as the
`claude_md` arm's `--append-system-prompt-file` (`scripts/pilot.py:804-817`), and every memory arm gets
**the same file byte for byte, prefixed by its memory instruction at the top** (`base.py:17-19`;
`adapters/claude_mem/adapter.py:787-796` shows the composition: instruction + `"\n\n"` + base prompt).
The instruction = `adapters/_shared/memory_protocol.md` verbatim with the `{search_instruction}` slot
filled by one sentence naming the arm's search mechanism, then `adapters/<arm>/instruction_appendix.md`
(`harness/instructions.py:130-184`; `assert_shared_protocol` at `:209-237` enforces it). The recall
appendix is 605 bytes (`adapters/recall/instruction_appendix.md`). Instruction bytes per arm are
printed by the dry run and published per run (`environment.json` keys `instruction_manifest`,
`instruction_arms_matched`).

### 3.6 Hooks (`claude_mem` and `supermemory` are the exercised pattern)

`adapters/claude_mem/adapter.py:731-785` (`_write_hook_settings`) rewrites the plugin's `hooks.json`
into `<config_dir>/settings.json` = `{"hooks": {<Event>: [{"matcher":..., "hooks":[{"type":"command",
"command": "node <config_dir>/claude-mem-hook-wrapper.js <Event> <base64 argv>", "shell": "bash"}]}]}}`;
the wrapper (`adapters/claude_mem/hook_wrapper.js`) runs the vendor command and appends one JSON line per
event to `CLAUDE_MEM_HOOK_LEDGER` (`<config_dir>/hook-ledger.jsonl`) with the fields the gate reads
(`event`, `exit_code`, `output_sha256`, `hook_error`; `harness/gate.py:172-178, 352-371`). `build()`
returns `ArmSpec(bare=False, config_dir=config_dir, config_dir_digest=digest_tree(config_dir),
extra_args=("--plugin-dir", ...), env={..., "HOME": <dir under config_dir>})` (`:849-877`) and
`admission_signal()` declares `required_hooks=("SessionStart","UserPromptSubmit","PostToolUse","Stop")`
(`:33, 896-900`). `bare=False` is mandatory with `config_dir` (`claude_exec.py:232-237`), and
`CLAUDE_CONFIG_DIR` is set from it (`:132-133`).

Two hard-coded couplings a memkernel hook arm would hit: the runner reads a hook ledger only for
`arm in ("supermemory", "claude_mem")` (`scripts/pilot.py:2543-2550`), and per-cell namespaces are
issued only for `claude_mem` (`cell_namespace`, `:1201-1211`; every other arm shares `args.namespace`
across all cells of a run). An arm whose integration writes during a session (hooks or a `retain` tool
the agent may call) therefore leaks across cells unless it is added to that branch.

### 3.7 Production isolation changes the wiring (important for the adapter design)

`scripts/pilot.py` imports only `run_isolated_claude_case` (`:149`) and runs every session through it
(`:2434-2442`); `docs/SECURE_EXECUTION.md:3-13, 36-40` says `run_claude_case()` remains for unit
fixtures only. Consequences, all in `harness/isolation.py`:
- the adapter's stdio MCP server command is **replaced** by a relay: every `mcpServers` entry becomes
  `{"command": "/usr/local/bin/python", "args": ["/usr/local/bin/mcp-relay"], "env":
  {"AMB_MEMORY_RELAY_URL": <memory broker>, "AMB_ALLOWED_TOOLS": <tools from extra_allowed_tools>}}`
  (`:906-956`); an empty tool allowlist is refused (`:933-937`);
- the memory broker forwards JSON-RPC (`initialize`, `tools/list`, `tools/call`) over HTTP to one
  `AMB_MEMORY_BROKER_UPSTREAM_URL` with `Authorization: Bearer` (`harness/broker.py:383-415`;
  `docker/compose.yaml:69-89`; `.env.example:95-97`, default `http://graphiti-mcp:8000/mcp`), or uses
  a native `graphiti` handler (`harness/broker_main.py:27-29`). So in the isolated path a memkernel
  server must be reachable as an HTTP MCP endpoint on the broker network, not spawned as stdio;
- `/usr/local/bin/mcp-relay` is referenced (`isolation.py:947`) but no file in the tree or in
  `docker/Dockerfile.participant` installs it (grep over the clone found only the reference);
- the participant env is allow-listed to `HOME, LANG, LC_ALL, LC_CTYPE, TERM, NO_COLOR, TMPDIR` plus
  `AMB_PUBLIC_*` (`:223-225, 1048-1055`); `HOME=/tmp` by default (`:1056`); `ANTHROPIC_BASE_URL` is
  overwritten to the model broker and `ANTHROPIC_AUTH_TOKEN` to a scoped capability token
  (`:1065-1074`); `config_dir` is copied to `/session/claude-config` and scanned for secrets
  (`:961-976`); the participant image is `python:3.12-slim` + Node 22 + `@anthropic-ai/claude-code@2.1.221`
  and nothing else (`docker/Dockerfile.participant:3-13`).

## 4. Ingest path (question b)

- **One call per arm per run, whole corpus.** `scripts/pilot.py:1839-1856`: for each arm in
  `SELF_INGESTING_ARMS` present in the run, `registry.get(arm).ingest(corpus, args.namespace)` once,
  before any session; `corpus = CorpusManifest.load(corpus_root)` (`:1842-1844`). recall arms call
  `ingest()` too, but it only verifies the out-of-band generation (`:1878-1891`).
- **The adapter reads the files itself** from `corpus.root / rel` for every manifest entry (recall
  `:781`; fs_grep `adapters/fs_grep/adapter.py:177-187`). Both existing adapters first run
  `harness.transcripts.render_corpus`, which converts each JSONL transcript into a markdown file named
  `notes__<16-hex>.md` derived only from the corpus path (`harness/corpus_names.py:26-43`;
  `harness/transcripts.py:58-72`), so the agent never sees a task, role or "stale" marker in a name
  (`corpus_names.py:1-8`).
- **Transcript format**: JSONL, one object per turn: `{"role", "content", "tool_name", "tool_input",
  "tool_result", "ts"}` (e.g. `corpus/sessions/ts-quote-shell/p01.jsonl`). 196 entries in
  `corpus/manifest.json` (40 `sessions/**`, 156 `distractors/*`), including the seven `xs-*` shards
  (`sessions/xs-evolve-lease/p01..p03.jsonl`, `xs-join-batch/p01..p02`, `xs-widen-manifest/p01..p02`).
  `docs/CROSS_SESSION_SYNTHESIS.md:107-112` ("manifest has not been rebuilt, so no arm ingests them")
  is stale on this commit.
- **"Neutral feed" in code** = (1) the same manifest bytes to every arm, verified by sha256 before
  ingest (`base.py:86-90, 132-141`; `README.md:80-81`); (2) neutral document names (`corpus_names.py`);
  (3) condition and run names hashed out of namespaces and work dirs (`corpus_names.py:52-71`); (4)
  the condition corpus is assembled outside the arms' view (`scripts/abstention.py:11-14`).
- `ingest_event` (`harness/lifecycle.py:146-188`) is **not** part of the grid feed; it is the optional
  per-source replay used by `scripts/lifecycle_verify.py` against `capabilities/lifecycle-temporal.json`
  (three `xs-evolve-lease` shards then an unchanged replay; `docs/LIFECYCLE_CAPABILITY.md:7-16`).
- FR-012 compatibility: nothing in the contract requires rendering; an adapter may hand the raw JSONL
  bytes to its write path. The two shipped adapters render first, so the preregistration should state
  which bytes memkernel's `retain(type="document")` receives.

## 5. Mechanism per lifecycle group

### 5.1 Cross-session carry-over (question c)

**Exists as "sequence mode"**, never run in a published measurement (`preregistration/006-longitudinal-suite.md:3`
"DRAFT"; `preregistration/084-sequence-selectivity.md:3` "COMMITTED before measurement. No measurement").

- Entry: `scripts/pilot.py --sequence-plan <json> --heldout-manifest <json>` (`:1328-1337`; both or
  neither, `:1478-1479`); `--tasks` is refused with a plan (`:1588-1589`); the manifest comes from
  `python -m scripts.freeze_evaluation --sequence-plan ... --tasks-root ...` and must bind every task
  file, checker, fixture tree and oracle of the plan (`harness/sequence_validation.py:66-111`;
  `harness/sequence_preflight.py:43-87`).
- Plan schema (`harness/sequence_plan.py:118-209`): `{"schema":1, "plan_id", "baseline_arm",
  "evaluation_manifest_id", "evaluation_manifest_digest", "arms":[...], "chains":[{"chain_id","seed",
  "sessions":[{"task_id","position","role","user_input"}]}]}`; roles `source` (first), `distance`
  (middle), `target` (last) (`:20, 185-188`); length >= 2 (`:176-177`); **a distinct task per session**
  (`:189-190`); a (task, seed) cell belongs to one chain (`:191-198`).
  `validate_plan` (`sequence_validation.py:114-204`) additionally requires length in `(2, 4, 8)`
  (`:19, 142-146`), every task `kind == "primary"` (`:155-159`), `user_input == tasks/<id>/task.json`
  prompt (`:160-164`), the source task to declare `fact_terms` (`:169-173`), and those terms to be
  absent from every later prompt, fixture tree and shared instruction file (`:174-186`).
- Execution (`harness/runner.py:213-256`): chains run concurrently, positions in order, position n+1
  only after every arm finished position n; each row goes through `run_grid` so a failure is a record.
  Scoring: `harness/sequence.py:379-527` (target success among admitted chains, chain admitted only if
  every session admitted; funnel labels and `memory_events` selectivity from the adapter-declared
  `memory_event_tools`, `harness/memory_events.py`).
- **What persists across the sessions of one chain, per arm** (`scripts/pilot.py` runner `:2392-2424`):
  - memory namespace: `sequence_namespace(base, chain_id, seed, arm)` = `f"{base}-seq-{sha256(chain_id)[:16]}-s{seed}-{arm}"`
    (`:1214-1223`), the same for every session of the chain, and the memory capability token is issued
    for that namespace (`:2416-2424`). **This is the only carrier**: whatever the product stores under
    that namespace through its own write path during session n is what session n+1 can read.
  - workspace: rebuilt for every session from `tasks/<task_id>/tree` (+ `dirty/`) into a fresh
    directory `work_root/work/sequence/<chain_digest>/<task_id>/s<seed>/<arm-token>` (`:2401-2404,
    2414`); `sandbox.restore` refuses a non-empty destination (`harness/sandbox.py:159-160`) and
    `git init`s a new baseline (`:174-185`). Nothing from session n's tree survives.
  - `CLAUDE_CONFIG_DIR` / hook state: a separate `ArmSpec` and config dir per (chain, task, seed, arm)
    at `config_root/sequence/<chain_digest>/<task_id>/<arm>` (`:1956-1966`), so a hook ledger, a
    sentinel file, or anything a hook writes under the config dir does not carry over.
  - `HOME` and process state: a new participant container per session with `HOME=/tmp`
    (`harness/isolation.py:644-720, 1056`).
  - `fs_grep`: its overlay in sequence mode is `staging/<sequence_namespace>/memory` (`:2409-2413`),
    but ingest only fills `staging/<args.namespace>/memory` (`:1850`); `sandbox.restore` raises
    `FileNotFoundError("memory overlay ... does not exist; ingest first")` (`harness/sandbox.py:196-198`).
    No harness step writes session n's transcript anywhere an arm can read it; raw streams go to
    `work_root/private-streams` (`:2374`). `tests/test_pilot_sequence_mode.py` has no fs_grep case.
- Verdict for **lc-retain**: *supported for an MCP-store arm* (memkernel writes with `retain` or its
  hooks into the chain namespace and reads it next session), with the caveats that (1) the chain
  must be two different task directories (session n and session n+1 are two `tasks/<id>/`), (2) the
  "source" task must declare `fact_terms` absent from the second fixture, (3) chain length must be
  2, 4 or 8 (a revised-fact variant with three sessions is not allowed: 2 -> 4 means two distance
  tasks), (4) `fs_grep` and `claude_md` carry nothing between sessions today, so FR-015's rule
  "`fs_grep`: the harness writes the first session's transcript to its grep directory" and
  "`claude_md`: whatever the agent wrote into files" both **need a harness extension** (a post-session
  hook that renders the finished session into the chain's `memory/` overlay, and a workspace
  carry-over option), and (5) the hook-ledger and per-cell-namespace branches are hard-coded to
  other arms (section 3.6).

### 5.2 Repository mutation between sessions (question d)

A task definition cannot mutate a fixture mid-task: one task = one `tree/` (+ optional `dirty/`
overlay applied after the baseline commit) restored fresh per session (`harness/sandbox.py:21-27,
163, 187-189`). But a chain already requires a distinct task per position (`sequence_plan.py:189-190`),
so "the repository changes between sessions" is expressed as **two task directories** with different
fixtures in one chain; the held-out manifest binds both trees and both oracles
(`sequence_validation.py:103-110`). Verdict for **lc-reval**: *mutation side supported without harness
change*; the carry-over side is identical to 5.1 (store yes, files no). The leakage rule
(`:174-181`) must be satisfied by the stale fact's terms, not by the new state.

### 5.3 Second namespace (question e)

Not expressible. The namespace is derived per chain and arm (`scripts/pilot.py:1214-1223`) or per
cell for `claude_mem` only (`:1201-1211`); a `SequenceSession` has no namespace field
(`harness/sequence_plan.py:32-37`); the memory capability token binds one namespace per session
(`:2416-2424`; `harness/broker.py:283-303`). The "tenant isolation" capability track is an **offline**
artifact check: `capabilities/isolation.json` (four probes, each `{probe_id, tenant, query,
expected_terms, gold_document_ids, canary_document_ids}`) verified by `scripts/capability_verify.py`
over a vendor-produced JSONL (`docs/CAPABILITY_TRACKS.md:21-30, 49-71`); it never starts a session.
`lc-wiki` additionally needs the workspace (the wiki directory) carried into session 2, which 5.1 shows
is reset. Verdict for **lc-wiki**: *needs extension* (per-session namespace override in the plan plus
workspace carry-over, or a within-session design).

### 5.4 Within-session compaction (question f)

- Session shape: one `claude -p <prompt>` with `--output-format stream-json --verbose`
  (`harness/claude_exec.py:257-258`); no `--max-turns`, no context flags (`:251-285`); the only bound
  is wall clock, `timeout_s` (dataclass default 1800, `:200`; pilot `--timeout` default 600,
  `scripts/pilot.py:1326`), after which the process tree is killed and the cell records a timeout
  (`claude_exec.py:766-774`), which the gate discards (`gate.py:409-410`) and which is never retried
  (`harness/memory_startup.py:235-238, 354-357`).
- Nothing in `harness/`, `adapters/` or `scripts/pilot.py` references compaction (grep for
  `compact` hits only a docstring in `adapters/recall_graph_fulltools/adapter.py:30`). The stream
  parser keeps every event (`claude_exec.py:288-310`), so a `system/compact_boundary` event would be
  preserved in the gzipped private stream but not interpreted or counted.
- Hooks: `--bare` skips hooks (`claude_exec.py:184-187`); hooks run only for an arm with
  `config_dir` + `bare=False` (`:189-194, 232-237`), via `CLAUDE_CONFIG_DIR` (`:132-133`;
  `/session/claude-config` in the container, `isolation.py:1066-1067`). A `settings.json` with
  `PreCompact`/`PostCompact` entries would be honoured by Claude Code 2.1.221 inside the container,
  but: (1) no adapter declares those events, and `required_hooks` admission reads a ledger only for
  `supermemory`/`claude_mem` (`scripts/pilot.py:2547`); (2) memkernel's template hooks import
  `memkernel` and open ChromaDB locally with `poetry run python` (`<memkernel>/templates/hooks/pre-compact.py:11-16, 20-45`;
  `session-start.py:1-20`; `post-compact.py:11-45`), and the participant image has neither memkernel
  nor poetry nor network beyond the brokers (`docker/Dockerfile.participant:3-13`;
  `docs/SECURE_EXECUTION.md:3-17`), so they cannot run as shipped; (3) whether a 600 s `-p` session
  reaches auto-compaction is not controllable from the harness.
- Verdict for **lc-compact**: *needs extension / unclear*: a knob to force or detect compaction
  (longer timeout, a `compact_boundary` counter in `transcript_fields`, `PreCompact`/`PostCompact` in
  `required_hooks` with a ledger shim) and a participant image or hook variant that can reach the
  memkernel store from inside the sandbox.

### 5.5 Summary table

| group | mechanism needed (FR-015) | state on `c1b15726` | evidence |
|---|---|---|---|
| lc-retain | first-session state carried into session n+1 | **partly supported**: store carry-over via chain namespace; files/overlay not carried; 2-4-8 chain lengths; two task dirs per pair | `pilot.py:1214-1223, 2401-2414`, `sandbox.py:159-198`, `sequence_validation.py:19,189-190` |
| lc-reval | carry-over + repo mutation between sessions | **mutation supported** (second task dir), carry-over as above | `sequence_plan.py:189-190`, `sequence_validation.py:103-110` |
| lc-wiki | workspace carried into a session under a second namespace | **needs extension** (no per-session namespace, workspace reset) | `sequence_plan.py:32-37`, `pilot.py:1214-1223`, `sandbox.py:159-163` |
| lc-compact | long session with `PreCompact`/`PostCompact` hooks inside the executor | **needs extension / unclear** (no compaction control, hooks need `config_dir` + ledger shim + runnable in image) | `claude_exec.py:184-194, 251-285`, `pilot.py:1326, 2547`, `Dockerfile.participant` |

## 6. Admission (question g)

`harness/gate.py::check_session` (`:269-419`) must find, for an MCP-server arm:

1. `metadata.init_present` true: the `system/init` event was observed (`:283-287`; set by
   `claude_exec.py:656`).
2. For every `mcp_tool_prefixes` entry, at least one tool in the session's tool list
   (`memory_tools_available` / `session_tools`, `claude_exec.py:639-642, 664-665`) starts with it
   (`:299-311`). Tool names are `mcp__<server_name>__<tool>`, so the prefix must match the server
   name in the `--mcp-config` file.
3. `mcp_server_errors` empty and every server in `mcp_servers` with status `connected` or `ready`
   (`CONNECTED_STATUSES`, `:64`; checks `:312-320`). `pending` or `failed` discards.
4. No tool of another arm present or called (`forbidden_prefixes`, `:322-338`).
5. `required_hooks` (hook arms only): ledger entry per event with `exit_code == 0`, nonempty
   `output_sha256`, no `hook_error` (`:340-371`); `PostToolUse` may be waived when no tool was called
   (`conditional_hooks`, `:343-351`).
6. `sandbox_paths` recorded present at session start (`:373-385`; runner records `["memory"]` if the
   dir exists, `pilot.py:2529-2531`).
7. `prompt_sha256` equals the arm's frozen prompt, per task (`:387-397`; runner computes it from the
   file actually used, `pilot.py:2532-2536`).
8. `record.error is None` (`:409-410`): timeouts, crashes and parse errors discard.
9. Cell level: every required arm admitted **and** identical `sandbox_digest` across the cell's arms
   (`_cell_digest_reason`, `:422-443`; `admit_cells`, `:482-559`); the digest is computed before the
   memory overlay lands (`sandbox.py:191-193`).
10. Diagnostic/checkpoint metadata must be absent for an ordinary arm (`:181-267`).

"Available is the gate; used is a finding": a present but never-called memory surface is admitted with
a note (`:19-27, 399-407`). Pre-session, `harness/memory_startup.py` can speak MCP to the configured
server (`initialize` + `tools/list`, `:63-75, 206`) and retry only `wiring`/`transport` failures, never
`timeout` (`:235-238, 336-425`); `scripts/pilot.py:1978-1990` additionally issues a real `tools/call`
preflight for recall arms. Every live run also writes `admission.json` with `admitted_cells`,
`discarded_cells`, `discarded_by_arm` and per-session verdicts (`gate.py:470-479`).

## 7. Cell count and how to compute it (question h)

- A cell is `(task_id, seed)` (`harness/schema.py:144`; `gate.py:504-514`); one `pilot.py` invocation
  runs `len(tasks) * len(seed_values)` cells x `len(arms)` sessions (`scripts/pilot.py:1653-1657`;
  seeds `range(args.seeds)` or `--seed-values`, `:1452-1455, 1861`).
- The **official grid is five `pilot.py` invocations**, one per corpus condition, driven by
  `scripts/abstention.py` (`:16, 355-388`; `scripts/launch_official.sh:143-147`), each with its own
  assembled corpus, namespace and `results/<run_id>-<condition>/`. The task roster per condition comes
  from plant declarations and a retirement list, not from `--tasks` (`abstention.py:146-157, 264-320`;
  `--tasks` is "for smoke tests only").
- `official-003` as preregistered (`preregistration/026-official-003-fair-instruction.md:20`):
  "73 task-conditions x 5 seeds x 8 arms = 2,920 sessions". Re-derived here from
  `results/official-003-*/records.final.jsonl` and `admission.json`: present 27 tasks (incl.
  `fa-dedup-key`), absent 12, superseded 11, contradictory 11, adjacent 12; seeds 0-4; 365 cells, 317
  admitted, 48 discarded (111+52+46+51+57 admitted; 24+8+9+4+3 discarded). `docs/STATUS.md:13-14`
  ("317 admitted cells, 26 tasks") counts distinct `ts-*` tasks.
- **On this commit** the same driver resolves 27 / 11 / 10 / 10 / 11 = **69 task-conditions**
  (section 2.4; the retirement list moved since official-003).
- `xs-*` tasks are not in any condition grid: `GRID_PREFIXES = ("ts-",)` (`pilot.py:1092`), selectable
  only with `--tasks ... --include-synthesis` (`:1109-1113, 1614-1615`), and refused together with
  `--condition` (`:1616-1617`, "supported only against the frozen base corpus"). They are a separate
  `pilot.py` invocation on `corpus/` (3 tasks).
- **Formula for the memkernel run** (arms `bare, claude_md, placebo, protocol, fs_grep, memkernel`, A = 6,
  S seeds):
  - cells = (69 task-conditions + 3 `xs-*`) x S = 72·S; sessions = 72·S·6 = 432·S.
  - S = 1: 72 cells, 432 sessions. S = 3 (pilot default): 216 cells, 1,296 sessions. S = 5 (official-003):
    360 cells, 2,160 sessions.
  - Using the official-003 roster instead (73 + 3 = 76 task-conditions): 456·S sessions (2,280 at S = 5).
  - Plus the lifecycle suite (FR-015) in sequence mode: sessions = sum of chain lengths x arms
    (`pilot.py:1653-1655`); chains must be 2, 4 or 8 long and each task may appear in one chain per seed.
- Commands that reproduce the numbers without credentials:
  `python -m scripts.abstention --dry-run --run-id probe --arms <arms> --memory-instruction protocol
  --conditions present,absent,superseded,contradictory,adjacent --seeds <S>` (per-condition task lists
  and session counts) and `python -m scripts.pilot --dry-run --arms <arms> --memory-instruction protocol
  --seeds <S> --tasks xs-evolve-lease,xs-join-batch,xs-widen-manifest --include-synthesis`. Both refuse
  until `memkernel` is registered (section 3.3).
- Token reference for budgeting (official-003 present condition, `results/official-003-present/costs.json`):
  `bare` 135 sessions, 2,057,703 input + 254,506 output tokens (about 15.2k in / 1.9k out per session);
  `claude_md` 2,057,084 / 230,084. Memory arms cost more: `README.md:64-65` reports recall at 4.5x input
  tokens and 2.6x wall time of the other arms in `pilot-004-placebo`. Prices are mandatory flags with
  no defaults (`docs/REPLICATION.md:62-64`); `--price-cache-read/--price-cache-creation` exist for
  providers that price cache separately.

## 8. Data safety (question i)

- **Declaration required**: `AMB_DATA_POLICY_FILE` for every live run (`docs/DATA_SAFETY.md:24-34`;
  loaded only when not `--dry-run`, `scripts/pilot.py:1893-1898`); schema version 1, `synthetic-only`,
  `retention: zero`, `training: false`, `reuse: false`, every hosted provider named
  (`docs/provider-policy.example.json`). Only its digest and non-secret declarations land in
  `environment.json` (`DATA_SAFETY.md:32-34`). The corpus must pass `python -m scripts.audit_data_safety`
  (`:3-7, 49-53`).
- **What a live run publishes** (`results/<run_id>/`): `admission.json`, `costs.json`,
  `environment.json`, `records.jsonl`, `records.final.jsonl`, `streams/` (as in `results/official-003-*`),
  plus `challenge.json`, `execution-events.jsonl` and a signed `adjudication.receipt.json`
  (`docs/SECURE_EXECUTION.md`, "Trusted adjudication receipt"; `README.md:151-159`), which needs
  `AMB_RUNNER_IMAGE_DIGEST`, `AMB_PARTICIPANT_AGENT_DIGEST`, a signing key file and a ledger file
  (`scripts/pilot.py:1793-1798`).
- **Receipt boundary**: records are written privately (`work_root/records.private.jsonl`, raw streams
  under `work_root/private-streams`, `pilot.py:2374, 2383`; `DATA_SAFETY.md:38-39`) and published as
  `harness.privacy.public_receipt` (`harness/privacy.py:126-182`): task, arm, seed, success, memory call
  counts, tokens, turns, wall time, cost, `config_dir_digest`, tool **names** only, safe metadata
  (`_SAFE_METADATA_FIELDS`, `:40-60`), and sha256 receipts of `user_input`, `response`, `reference`,
  `retrieved_contexts`, `conversation`, `runtime_decisions`, `hook_ledger`, `tool_calls` (`:168-179`).
  `RAW_RECORD_FIELDS` (`:25-36`) and raw tool fields (`args`, `output`, `file_path`, `command`,
  `old_string`, `new_string`, `stderr`, `:37-39`) are refused if they reappear (`assert_public_receipt`,
  `:185-200`). Any log that is ever published must pass `redact_log_text` (`:215`; `DATA_SAFETY.md:44-47`).
- Session path hygiene: `launch_official.sh:112-136` refuses to start when the checkout, the CLI or the
  palace root sit under a home directory, because absolute paths end up in the model's own words.
- Replication report fields (`docs/REPLICATION.md:66-80`): run id, commit sha, model/provider/CLI
  version, arms, seeds, admitted **and discarded** cells, prices.

## 9. Model selection (question j)

- Flags: `--model` (default `deepseek/deepseek-v4-flash`, `scripts/pilot.py:1308`) is passed straight
  to the CLI as `--model` (`claude_exec.py:266-267`); `--base-url` (default `https://openrouter.ai/api`,
  `:1309`) becomes `ANTHROPIC_BASE_URL`, with `ANTHROPIC_AUTH_TOKEN` and `ANTHROPIC_API_KEY` set empty
  (`:2327-2329`); the session env is an allow-list, not a copy (`claude_exec.py:104-134`).
- `OPENROUTER_API_KEY` is required for every non-dry, non-prepare run regardless of provider
  (`:1472-1473`).
- In the isolated path the participant never sees that key: `ANTHROPIC_BASE_URL` is overwritten to the
  model broker and `ANTHROPIC_AUTH_TOKEN` to a scoped token (`isolation.py:1065-1074`); the broker
  forwards the Messages request to `AMB_MODEL_BROKER_UPSTREAM_URL` (default
  `https://openrouter.ai/api/v1/messages`, `.env.example:95`) with headers rebuilt as
  `Content-Type` + `Authorization: Bearer <AMB_BROKER_UPSTREAM_CREDENTIAL>` (`harness/broker.py:393-402,
  424-432`) through the egress proxy whose allowlist defaults to `api.openai.com,openrouter.ai`
  (`.env.example:99`). `scripts/openrouter_anthropic_gateway.py` is the published deterministic route
  (frozen model + provider order, `:1-30`).
- **A Claude model through Anthropic**: nothing forbids `--model claude-...` and an upstream of
  `https://api.anthropic.com/v1/messages`, but it is untested here and three things must be verified:
  the broker drops client headers (`anthropic-version`, `anthropic-beta`) and sends `Bearer` rather
  than `x-api-key`; `api.anthropic.com` must be added to the egress allowlist; the pricing flags must
  carry Anthropic's cache-read/creation rates. `docs/REPLICATION.md:75` classes a different model as
  "an extension, which is welcome, but not a replication", and the data policy must name the provider.
  `.env.example:3-7` documents the non-isolated `ANTHROPIC_BASE_URL/AUTH_TOKEN` route, which
  `pilot.py` no longer uses.

## 10. Open questions

1. **Isolation is mandatory and the relay is missing.** `pilot.py` only runs sessions through
   `run_isolated_claude_case` (`:149, 2434-2442`): Linux host with rootless Docker, participant and
   checker image digests, broker signing secret (`:1899-1903`), adjudicator key, `AMB_DATA_POLICY_FILE`.
   The relay binary `/usr/local/bin/mcp-relay` referenced at `isolation.py:947` exists nowhere in the
   tree or the participant Dockerfile (introduced 2026-09-12, commit `755e68d9`, after official-003).
   Whether a stdio MCP arm (recall, memkernel) can run end to end on this commit is unverified.
2. **How a memkernel MCP server is reached.** In the isolated path the adapter's stdio command is
   replaced by the relay and the memory broker forwards to one HTTP upstream
   (`isolation.py:941-954`; `broker.py:383-415`; `compose.yaml:84-85`). memkernel's shipped integration
   is a stdio server (`templates/`), so the adapter must either host it as an HTTP MCP endpoint on the
   broker network and set `MEMKERNEL_PROJECT_ID` per namespace server-side, or the harness needs a
   stdio-capable broker. Does the broker pass the session namespace to the upstream?
   (`broker.py:283-303` issues a namespace-scoped capability; the upstream call at `:393-402` carries
   only the JSON-RPC body.)
3. **Hook ledger and per-cell namespace are hard-coded to other arms** (`pilot.py:2547, 1209`).
   Registering memkernel needs edits to `ARMS`, `adapter_for`, `MEMORY_ARMS`, `SELF_INGESTING_ARMS`,
   `memory_instructions`, plus those two branches if hooks or per-cell write isolation are used.
4. **Write path during grid sessions.** The official grid assumes arms are read-only after ingest
   (`README.md:52-54`, `docs/STATUS.md:34-36`); memkernel's `retain` tool is callable by the agent and
   its hooks write at session start. With a shared `args.namespace` across cells, writes leak between
   cells. Either withhold write tools in `allowed_tools` for the grid (recall withholds every write
   tool, `config.frozen.json:31`) or request per-cell namespaces.
5. **Which bytes are "verbatim".** Shipped adapters render JSONL to neutral-named markdown before
   indexing (`transcripts.py`); FR-012 says raw transcript bytes. Decide and state it.
6. **Sequence mode has never been run.** Plan JSON format is validated (tests exist:
   `tests/test_pilot_sequence_mode.py`, `test_sequence_*.py`) but no committed plan exists and
   `fs_grep` cannot run in a chain without an ingest step. Harness extensions needed for FR-015 as
   written: post-session transcript-to-overlay for `fs_grep`, optional workspace carry-over
   (`claude_md`, `lc-wiki`), per-session namespace override (`lc-wiki`), chain lengths other than
   2/4/8 or a 4-chain with two distance tasks for the revised-fact variant, compaction control and
   `PreCompact`/`PostCompact` ledgering (`lc-compact`).
7. **Hook runtime inside the sandbox.** memkernel's template hooks need the `memkernel` package and a
   local ChromaDB path; the participant image is `python:3.12-slim` + Node + Claude Code with network
   only to the brokers. A hook variant that talks to the relay, or a custom participant image, is
   required; both change the pinned image digest.
8. **Compaction in `-p` mode.** No evidence in the repository either way on whether a single-prompt
   session of <= 600 s auto-compacts; needs a measured probe before `lc-compact` tasks are designed.
9. **Anthropic upstream through the broker** (section 9): header rewriting and egress allowlist are
   unverified for `api.anthropic.com`.
10. `scripts/abstention.py --dry-run` writes `corpus/conditions/*` into the checkout (gitignored);
    note it in the preregistration so a "dry run touches nothing" claim is not made for that driver.

## 11. Budget: formula, prices and the measurement still needed (revised 2026-10-15)

The published official-003 ledger ran Claude Code against `deepseek/deepseek-v4-flash` through
OpenRouter. Same executor, different model and tokenizer, and its `costs.json` input figure does not
separate cache reads and cache writes, which dominate a Claude Code session. Its per-session numbers
are therefore **not** carried over to a Claude model here. What is fixed now is the formula and the
prices; the per-session usage comes from a short paid pilot through the real executor before the
preregistration.

Grid on this commit: 69 task-conditions + 3 `xs-*` = 72 cells per seed; arms `bare`, `claude_md`,
`placebo`, `protocol`, `fs_grep` (five control-type arms) and `memkernel` (one memory arm).

Formula, per seed S:

    sessions_control = 72 × S × 5
    sessions_memory  = 72 × S × 1
    cost = Σ over arm types of sessions × (in_tok × p_in + cache_write_tok × p_cw + cache_read_tok × p_cr + out_tok × p_out)

with `in_tok`, `cache_write_tok`, `cache_read_tok`, `out_tok` the **measured** per-session means for
that arm type from the pilot's usage records, and a 20 percent allowance for discarded
wiring-failure cells (paid, never retried).

Prices (USD per million tokens) from https://platform.claude.com/docs/en/about-claude/pricing,
fetched 2026-10-15:

| model | base input | 5m cache write | cache read | output |
|---|---|---|---|---|
| Claude Sonnet 5.5 | 2.00 | 2.50 | 0.10 | 10.00 |
| Claude Opus 5.5 | 4.00 | 5.00 | 0.20 | 20.00 |
| Claude Haiku 5.5 (prompt ≤ 100k) | 0.10 | 0.125 | 0.01 | 0.50 |
| Claude Haiku 5.5 (prompt > 100k) | 0.50 | 0.625 | 0.05 | 2.50 |

(The ≈ 1:20 Sonnet-to-Haiku gap is the published price ratio, not an arithmetic slip; the earlier
table is withdrawn anyway because its per-session inputs were not Claude measurements.)

**Pilot to measure usage** (prerequisite for the preregistration budget): the same executor path,
the chosen Claude model, two cells per arm type (one `present`, one `superseded`), one seed; take
per-session means of the four token classes from the usage records; multiply out with the formula;
record the pilot run id in the preregistration. Expected order of magnitude stays tens to low
hundreds of dollars for S = 3 at these prices even at several times a 15k-input session, so the
go/hold decision rests on the harness questions in section 10, not on cost; that expectation is
confirmed or corrected by the pilot, not assumed.

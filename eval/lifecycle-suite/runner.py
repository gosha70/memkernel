#!/usr/bin/env python3
# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""Lifecycle runner for memkernel's maintainer-run supplemental evaluation.

Scope (specs/memkernel-0-5 FR-011): orchestrate the four lifecycle groups
only. A trial is one (task, arm, run) chain of sessions. Between sessions the
runner applies the arm's frozen persistence rule (FR-012) and nothing else;
each session runs ``claude -p ... --output-format stream-json`` in a fresh
process with a fresh HOME and CLAUDE_CONFIG_DIR. After the last session the
task's checker grades the workspace. Every session yields one receipt
(FR-018); raw streams stay under the run root, which must lie outside any git
checkout. This module never runs the agent-memory-bench retrieval grid and
computes no statistics; ``report.py`` does the counting from receipts.

    runner.py run --tasks-root DIR --task ID ... --arm NAME ... --runs N --run-root DIR
                  --phase calibration|measured --model M --code-sha SHA [--preregistration FILE]
                  --memkernel-cmd PATH --memkernel-python PATH
    runner.py demo        # credential-free, scripted stub agent (FR-014)
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import secrets
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import uuid
from collections import Counter
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

import corrections
from checker_support import kill_user_processes
from diagnostics import WIKI_DIR, read_paths, session_diagnostics
from records import (
    CONNECTED_STATUSES,
    SCHEMA_VERSION,
    StreamSummary,
    render_transcript,
    sha256_bytes,
    sha256_text,
    summarise,
    tool_counts,
    tool_payload_digest,
    utc_now,
    validate_receipt,
)

if TYPE_CHECKING:
    import curator

SUITE_DIR = Path(__file__).resolve().parent
REPO_ROOT = SUITE_DIR.parents[1]
ARMS_DIR = SUITE_DIR / "arms"
HOOK_SCRIPTS = {
    "SessionStart": "session-start.py",
    "PreCompact": "pre-compact.py",
    "PostCompact": "post-compact.py",
}
BASE_TOOLS = ("Read", "Grep", "Glob", "Bash", "Write", "Edit")
ARM_NAMES = (
    "bare",
    "placebo",
    "protocol",
    "claude_md",
    "fs_grep",
    "memkernel",
    "wiki_studio",
    "memkernel_governed",  # memkernel-0-16-lifecycle-corrections FR-004: the composition arm, scripted curator
    "memkernel_governed_oracle",  # its upper bound, the oracle curator (decision B6)
    "informed",  # the calibration's informed reference (decision B3)
)
CORRECT_GROUP = "lc-correct"
CORRECT_CALIBRATION_ARMS = ("bare", "informed")  # FR-003: the only arms an lc-correct calibration runs and grades
CORRECTION_BRIEF_TOKEN = "{correction_brief}"
GOVERNED_PROPOSALS_DIR = "doc_internal/proposals"
HELPER_TIMEOUT_S = 300.0  # a correction helper (memkernel_ops.py, the wiki-studio CLI) that runs longer is a failure
GATE_UNCHECKED: dict[str, Any] = {  # a gate check that could not run: no evidence, and the trial is invalid
    "landed": [],
    "approved": [],
    "unreviewed_drafts": [],
    "breaches": [],
    "lint_violations": 0,
}
COMPACT_PROMPT = "/compact"
CALIBRATION_PHASE = "calibration"
MEASURED_PHASE = "measured"
STREAM_FILE = "stream.jsonl"
PRIMARY_NAMESPACE = "primary"
MEMORY_DIR_TOKEN = "{memory_dir}"
ENV_PASSTHROUGH = ("PATH", "LANG", "LC_ALL", "TMPDIR", "ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL")


# ── arms and tasks ────────────────────────────────────────────


@dataclass(frozen=True)
class Arm:
    name: str
    persist_workspace: bool
    persist_transcripts: bool
    persist_store: bool
    instruction: bytes
    allowed_tools: tuple[str, ...]
    mcp: bool
    hooks: tuple[str, ...]
    config_sha256: str
    groups: tuple[str, ...] = ()  # empty: every group; otherwise the only groups this arm runs on (FR-012)
    cli_pin: tuple[str, str] | None = None  # (command, version) that must be on the session PATH for a paid run
    carry: tuple[str, ...] = ()  # workspace paths kept from the previous session besides the shared artifact
    wiki_governed: bool = False  # MEMKERNEL_WIKI_MODE=governed, proposals beside the wiki; gate check at the end
    phases: tuple[str, ...] = ()  # empty: every phase; otherwise the only phases this arm may run in

    def runs_on(self, task: Task) -> bool:
        return not self.groups or task.group in self.groups


def load_arm(name: str, arms_dir: Path = ARMS_DIR) -> Arm:
    config_path = arms_dir / name / "config.frozen.json"
    raw = config_path.read_bytes()
    config = json.loads(raw)
    instruction = (arms_dir / name / config["instruction"]).read_bytes() if config.get("instruction") else b""
    hashed = raw + b"\0" + instruction
    if config.get("curator_policy"):  # the governed arms: the policy is part of the treatment (FR-004, D3)
        policy = (arms_dir / name / config["curator_policy"]).read_bytes()
        if sha256_bytes(policy) != config.get("curator_policy_sha256"):
            raise ValueError(f"{name}: {config['curator_policy']} does not match its pinned curator_policy_sha256")
        hashed += b"\0" + policy  # arms without a policy keep the hash they always had
    persist = config["persist"]
    return Arm(
        name=name,
        persist_workspace=bool(persist["workspace"]),
        persist_transcripts=bool(persist["transcripts"]),
        persist_store=bool(persist["store"]),
        instruction=instruction,
        allowed_tools=tuple(config["allowed_tools"]),
        mcp=bool(config.get("mcp", False)),
        hooks=tuple(config.get("hooks", [])),
        config_sha256=sha256_bytes(hashed),
        groups=tuple(config.get("groups", [])),
        cli_pin=(config["cli_pin"]["command"], config["cli_pin"]["version"]) if config.get("cli_pin") else None,
        carry=tuple(config.get("carry", [])),
        wiki_governed=bool(config.get("wiki_governed", False)),
        phases=tuple(config.get("phases", [])),
    )


@dataclass(frozen=True)
class Step:
    stage: str  # exposure | work | evaluation | compact
    prompt: str


@dataclass(frozen=True)
class SessionSpec:
    steps: tuple[Step, ...]
    overlay: str | None
    remove: tuple[str, ...]
    namespace: str


@dataclass(frozen=True)
class Task:
    task_id: str
    group: str
    root: Path
    sessions: tuple[SessionSpec, ...]
    shared_artifact: str | None
    correction: dict[str, Any] | None = None  # lc-correct: delivered to the session after ``after_session``

    def brief_for(self, position: int) -> str | None:
        """The correction brief once the correction has happened (sessions after ``after_session``), else None."""
        if self.correction is None or position <= int(self.correction["after_session"]):
            return None
        return corrections.brief_text(self.correction)

    @property
    def tree(self) -> Path:
        return self.root / "tree"

    def oracle_dir(self, oracles_root: Path) -> Path:
        return oracles_root / self.task_id


def load_task(task_dir: Path) -> Task:
    spec = json.loads((task_dir / "task.json").read_text(encoding="utf-8"))
    sessions = []
    for raw in spec["sessions"]:
        steps = tuple(
            Step(stage="compact", prompt=COMPACT_PROMPT) if step.get("compact") else Step(step["stage"], step["prompt"])
            for step in raw["steps"]
        )
        sessions.append(
            SessionSpec(
                steps=steps,
                overlay=raw.get("overlay"),
                remove=tuple(raw.get("remove", [])),
                namespace=raw.get("namespace", PRIMARY_NAMESPACE),
            )
        )
    return Task(
        task_id=spec["task_id"],
        group=spec["group"],
        root=task_dir,
        sessions=tuple(sessions),
        # lc-correct names its shared state ``exposure_artifact`` (FR-002): copied from the session before the
        # correction, before the correction is delivered, so the copy carries the exposure state only.
        shared_artifact=spec.get("shared_artifact") or spec.get("exposure_artifact"),
        correction=spec.get("correction"),
    )


# ── persistence between sessions (FR-012) ─────────────────────


@dataclass
class ChainState:
    """What a finished session leaves behind for the next one in its chain."""

    workspace: Path | None = None
    transcripts: list[Path] = field(default_factory=list)


@dataclass(frozen=True)
class SessionDirs:
    root: Path
    workspace: Path
    home: Path
    config: Path
    memory_dir: Path | None
    store: Path | None
    namespace: str


def prepare_session(task: Task, arm: Arm, position: int, chain_dir: Path, state: ChainState) -> SessionDirs:
    """Build the directories session ``position`` starts from, carrying only what ``arm``'s rule permits."""
    session = task.sessions[position]
    root = chain_dir / f"s{position}"
    workspace, home, config = root / "workspace", root / "home", root / "config"
    if arm.persist_workspace and state.workspace is not None:
        shutil.copytree(state.workspace, workspace, symlinks=True)
    else:
        shutil.copytree(task.tree, workspace, symlinks=True)
        if task.shared_artifact and state.workspace is not None:
            source = state.workspace / task.shared_artifact
            if source.exists():
                target = workspace / task.shared_artifact
                if target.exists():
                    shutil.rmtree(target)
                shutil.copytree(source, target, symlinks=True)
        if state.workspace is not None:
            for rel in arm.carry:  # the governed arms' gate receipts (decision B7)
                source = state.workspace / rel
                if source.exists() and not (workspace / rel).exists():
                    shutil.copytree(source, workspace / rel, symlinks=True)
    for rel in session.remove:
        target = workspace / rel
        if target.is_dir():
            shutil.rmtree(target)
        elif target.exists():
            target.unlink()
    if session.overlay:
        shutil.copytree(task.root / "overlays" / session.overlay, workspace, dirs_exist_ok=True)
    home.mkdir(parents=True)
    config.mkdir(parents=True)

    memory_dir = None
    if arm.persist_transcripts:
        memory_dir = chain_dir / "memory"
        memory_dir.mkdir(exist_ok=True)
        for index, transcript in enumerate(state.transcripts):
            shutil.copyfile(transcript, memory_dir / f"session-{index}.md")

    store = None
    if arm.persist_store:
        store = chain_dir / "store" / session.namespace
        store.mkdir(parents=True, exist_ok=True)
    return SessionDirs(root, workspace, home, config, memory_dir, store, session.namespace)


# ── one session ───────────────────────────────────────────────


@dataclass
class RunConfig:
    run_root: Path
    run_id: str
    phase: str
    model: str
    code_sha: str
    preregistration_sha256: str | None
    agent_cmd: tuple[str, ...]
    memkernel_cmd: str
    memkernel_python: str
    tasks_root: Path
    oracles_root: Path
    timeout_s: float = 900.0
    hook_command_override: tuple[str, ...] | None = None  # demo: record hooks without running memkernel
    shared_cache: Path | None = None
    ops_command: tuple[str, ...] | None = None  # memkernel_ops.py's command; default: memkernel_python + the script
    wiki_studio_cmd: str = "wiki-studio"  # the governed arms' curator CLI (pinned by the arm's cli_pin)
    # Blinding (the #90 review): what the agent's user may read. The hook scripts and the ledger run as the agent,
    # so in the image they come from a world-readable copy; with agent_uid set, each session's files belong to the
    # agent only while it runs, and everything else under the run stays the harness's.
    hooks_dir: Path = REPO_ROOT / "templates" / "hooks"
    ledger_script: Path = SUITE_DIR / "hook_ledger.py"
    agent_uid: int | None = None
    agent_gid: int | None = None


def _ops_command(cfg: RunConfig) -> tuple[str, ...]:
    return cfg.ops_command or (cfg.memkernel_python, str(SUITE_DIR / "memkernel_ops.py"))


def _instruction_file(arm: Arm, dirs: SessionDirs, brief: str | None = None) -> Path | None:
    if not arm.instruction:
        return None
    text = arm.instruction.decode("utf-8")
    if CORRECTION_BRIEF_TOKEN in text:  # the informed reference: its instruction exists only once the rule changed
        if brief is None:
            return None
        text = text.replace(CORRECTION_BRIEF_TOKEN, brief)
    if dirs.memory_dir is not None:
        text = text.replace(MEMORY_DIR_TOKEN, str(dirs.memory_dir))
    path = dirs.root / "instruction.md"
    path.write_text(text, encoding="utf-8")
    return path


def _memkernel_env(dirs: SessionDirs, chain_id: str, cfg: RunConfig, governed: bool = False) -> dict[str, str]:
    assert dirs.store is not None
    env = {
        "MEMKERNEL_PROJECT_ID": f"lc_{sha256_text(chain_id + '/' + dirs.namespace)[:16]}",
        "MEMKERNEL_CHROMA_PERSIST_PATH": str(dirs.store),
        # memkernel 0.7's sync ledger: beside the store and carried with it, outside Chroma's directory, and never
        # in the workspace (a relative default would land in the agent's working directory).
        "MEMKERNEL_STATE_DIR": str(dirs.store.with_name(f"{dirs.store.name}.state")),
        "MEMKERNEL_PROJECT_ROOT": str(dirs.workspace),
        "MEMKERNEL_WIKI_DIR": str(dirs.workspace / WIKI_DIR),
        "HOME": str(dirs.home),
    }
    if governed:  # the composition arms (FR-004): exports go through the gate, proposals sit where the curator's do
        env["MEMKERNEL_WIKI_MODE"] = "governed"
        env["MEMKERNEL_WIKI_PROPOSALS_DIR"] = str(dirs.workspace / GOVERNED_PROPOSALS_DIR)
    if cfg.shared_cache is not None:
        env["HF_HOME"] = str(cfg.shared_cache / "huggingface")
        # The cache is the model's only source: never contact the Hub, so the embedding model cannot change
        # between calibration and the measured run (the image pins the cached revision).
        env["HF_HUB_OFFLINE"] = "1"
    return env


def _write_wiring(
    arm: Arm, dirs: SessionDirs, chain_id: str, cfg: RunConfig, ledger: Path, brief: str | None = None
) -> list[str]:
    args: list[str] = []
    if arm.mcp:
        server_env = _memkernel_env(dirs, chain_id, cfg, arm.wiki_governed)
        mcp = {"mcpServers": {"memkernel": {"command": cfg.memkernel_cmd, "args": [], "env": server_env}}}
        mcp_path = dirs.root / "mcp.json"
        mcp_path.write_text(json.dumps(mcp, indent=2), encoding="utf-8")
        args += ["--mcp-config", str(mcp_path), "--strict-mcp-config"]
    if arm.hooks:
        hooks: dict[str, Any] = {}
        for event in arm.hooks:
            target = (
                list(cfg.hook_command_override)
                if cfg.hook_command_override
                else [cfg.memkernel_python, str(cfg.hooks_dir / HOOK_SCRIPTS[event])]
            )
            command = [
                sys.executable,
                str(cfg.ledger_script),
                "--ledger",
                str(ledger),
                "--event",
                event,
                "--",
                *target,
            ]
            hooks[event] = [
                {"matcher": "", "hooks": [{"type": "command", "command": " ".join(_quote(c) for c in command)}]}
            ]
        settings_path = dirs.root / "settings.json"
        settings_path.write_text(json.dumps({"hooks": hooks}, indent=2), encoding="utf-8")
        args += ["--settings", str(settings_path)]
    instruction = _instruction_file(arm, dirs, brief)
    if instruction is not None:
        args += ["--append-system-prompt-file", str(instruction)]
    if dirs.memory_dir is not None:
        args += ["--add-dir", str(dirs.memory_dir)]
    return args


def _quote(value: str) -> str:
    return "'" + value.replace("'", "'\\''") + "'"


def _session_env(arm: Arm, dirs: SessionDirs, chain_id: str, cfg: RunConfig) -> dict[str, str]:
    env = {key: os.environ[key] for key in ENV_PASSTHROUGH if key in os.environ}
    env.update({"HOME": str(dirs.home), "CLAUDE_CONFIG_DIR": str(dirs.config)})
    if arm.persist_store:
        env.update(_memkernel_env(dirs, chain_id, cfg, arm.wiki_governed))  # hooks read the server's MEMKERNEL_*
    return env


def _helper_env(arm: Arm, dirs: SessionDirs, chain_id: str, cfg: RunConfig) -> dict[str, str]:
    """The environment the correction's helpers run in: the session's, without the API key (no model is called)."""
    env = {key: value for key, value in _session_env(arm, dirs, chain_id, cfg).items() if key != "ANTHROPIC_API_KEY"}
    return env


def _ops(arm: Arm, dirs: SessionDirs, chain_id: str, cfg: RunConfig) -> curator.Ops:
    env = _helper_env(arm, dirs, chain_id, cfg)

    def call(*args: str) -> dict[str, Any]:
        try:
            completed = subprocess.run(
                [*_ops_command(cfg), *args],
                cwd=dirs.workspace,
                env=env,
                capture_output=True,
                text=True,
                check=False,
                timeout=HELPER_TIMEOUT_S,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise corrections.CorrectionError(f"memkernel_ops {args[0]} did not finish: {exc}") from exc
        if completed.returncode != 0:
            raise corrections.CorrectionError(
                f"memkernel_ops {args[0]} exited {completed.returncode}: {completed.stderr.strip()[-500:]}"
            )
        try:
            result: dict[str, Any] = json.loads(completed.stdout.strip().splitlines()[-1])
        except (IndexError, json.JSONDecodeError) as exc:
            raise corrections.CorrectionError(f"memkernel_ops {args[0]} printed no JSON") from exc
        return result

    return call


def _cli(arm: Arm, dirs: SessionDirs, chain_id: str, cfg: RunConfig) -> curator.Cli:
    env = _helper_env(arm, dirs, chain_id, cfg)
    base = [
        cfg.wiki_studio_cmd,
        "--root",
        str(dirs.workspace),
        "--wiki-dir",
        str(dirs.workspace / WIKI_DIR),
        "--proposals-dir",
        str(dirs.workspace / GOVERNED_PROPOSALS_DIR),
    ]

    def call(verb: str, *args: str) -> tuple[int, str]:
        try:
            completed = subprocess.run(
                [base[0], verb, *base[1:], *args],
                cwd=dirs.workspace,
                env=env,
                capture_output=True,
                text=True,
                timeout=HELPER_TIMEOUT_S,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise corrections.CorrectionError(f"{cfg.wiki_studio_cmd} {verb} did not finish: {exc}") from exc
        return completed.returncode, completed.stdout + completed.stderr

    return call


SESSIONS_DIR = "sessions"  # under the run directory: where a session runs, under a name that tells nothing


def _sessions_area(cfg: RunConfig) -> Path:
    return cfg.run_root / cfg.run_id / SESSIONS_DIR


def stage_session(dirs: SessionDirs, cfg: RunConfig) -> SessionDirs:
    """Move a prepared session (built in ``<chain>/s<n>``) into ``sessions/<random>`` for the agent's run.

    The agent's working directory then names neither the task nor the arm, nothing of the chain sits beside it (no
    ``../../s0``), and its store, the store's state and the grep directory come with it under the same name.
    """
    area = _sessions_area(cfg)
    area.mkdir(mode=0o711, exist_ok=True)
    token = area / secrets.token_hex(6)
    shutil.move(str(dirs.root), token)
    memory = store = None
    if dirs.memory_dir is not None:
        memory = token / "memory"
        shutil.move(str(dirs.memory_dir), memory)
    if dirs.store is not None:
        store = token / "store" / dirs.store.name
        store.parent.mkdir()
        shutil.move(str(dirs.store), store)
        state = dirs.store.with_name(f"{dirs.store.name}.state")
        if state.exists():
            shutil.move(str(state), store.with_name(f"{store.name}.state"))
    return SessionDirs(token, token / "workspace", token / "home", token / "config", memory, store, dirs.namespace)


def unstage_session(staged: SessionDirs, home: SessionDirs) -> None:
    """Move a finished session back to where the chain keeps it: the reverse of :func:`stage_session`."""
    if staged.store is not None and home.store is not None:
        shutil.move(str(staged.store), home.store)
        state = staged.store.with_name(f"{staged.store.name}.state")
        if state.exists():
            shutil.move(str(state), home.store.with_name(f"{home.store.name}.state"))
        staged.store.parent.rmdir()
    if staged.memory_dir is not None and home.memory_dir is not None:
        shutil.move(str(staged.memory_dir), home.memory_dir)
    shutil.move(str(staged.root), home.root)


def _own(path: Path, uid: int, gid: int, mode: int | None = None) -> None:
    """chown ``path`` and everything under it, links not followed; then ``mode`` on ``path`` itself."""
    for current, dirnames, filenames in os.walk(path):
        for name in [*dirnames, *filenames]:
            os.chown(os.path.join(current, name), uid, gid, follow_symlinks=False)
    os.chown(path, uid, gid, follow_symlinks=False)
    if mode is not None:
        os.chmod(path, mode)


@dataclass
class StepResult:
    lines: list[dict[str, Any]]
    started_at: str
    timed_out: bool
    spawn_failed: bool


def _run_step(cmd: list[str], cwd: Path, env: dict[str, str], timeout_s: float, raw: Path) -> StepResult:
    """Run one step; the deadline is enforced by the main thread whether or not the process prints."""
    import queue
    import threading

    started = utc_now()
    lines: list[dict[str, Any]] = []
    try:
        proc = subprocess.Popen(  # its own process group, killed whole once the step is over
            cmd, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, start_new_session=True
        )
    except OSError:
        return StepResult(lines, started, timed_out=False, spawn_failed=True)
    assert proc.stdout is not None
    stream = proc.stdout
    pending: queue.Queue[str | None] = queue.Queue()

    def pump() -> None:
        for line in stream:
            pending.put(line)
        pending.put(None)

    threading.Thread(target=pump, daemon=True).start()
    deadline = time.monotonic() + timeout_s
    timed_out = False
    with raw.open("a", encoding="utf-8") as sink:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                break
            try:
                line = pending.get(timeout=remaining)
            except queue.Empty:
                timed_out = True
                break
            if line is None:
                break
            text = line.strip()
            if not text:
                continue
            try:
                event = json.loads(text)
            except json.JSONDecodeError:
                event = {"type": "unparsed"}
            wrapped = {"ts": utc_now(), "event": event}
            lines.append(wrapped)
            sink.write(json.dumps(wrapped) + "\n")
    if not timed_out:
        # EOF on stdout does not mean the process has exited: keep the same deadline for the exit.
        try:
            proc.wait(timeout=max(0.0, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            timed_out = True
    if timed_out:
        proc.kill()
        proc.wait()
    with contextlib.suppress(ProcessLookupError, PermissionError):  # whatever the step left in its group ends with it
        os.killpg(proc.pid, signal.SIGKILL)
    return StepResult(lines, started, timed_out=timed_out, spawn_failed=False)


def _read_ledger(ledger: Path) -> list[dict[str, Any]]:
    if not ledger.exists():
        return []
    return [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines() if line.strip()]


@dataclass
class SessionOutcome:
    receipt: dict[str, Any]
    summary: StreamSummary
    dirs: SessionDirs
    prompts: list[str]
    timed_out: bool
    ran_in: Path | None = None  # the staged workspace the agent worked in, which its tool calls name


def run_session(
    task: Task,
    arm: Arm,
    run_index: int,
    position: int,
    chain_dir: Path,
    state: ChainState,
    earlier_reads: set[str],
    cfg: RunConfig,
    observe: Any = None,
) -> SessionOutcome:
    chain_id = chain_dir.name
    session = task.sessions[position]
    started_at = utc_now()
    t0 = time.monotonic()
    invalid: str | None = None
    summary = StreamSummary()
    prompts: list[str] = []
    timed_out = False
    exposure_at = evaluation_at = None
    hooks: list[dict[str, Any]] = []
    try:
        dirs = prepare_session(task, arm, position, chain_dir, state)
    except OSError:
        dirs = SessionDirs(
            chain_dir / f"s{position}",
            chain_dir / f"s{position}" / "workspace",
            Path(),
            Path(),
            None,
            None,
            session.namespace,
        )
        invalid = "fixture_restore_failed"
    home = dirs  # where the chain keeps this session; the agent runs it staged under a neutral name
    if invalid is None:
        dirs = stage_session(home, cfg)
    if observe is not None and invalid is None:
        observe(task, arm, position, dirs)  # before any correction: what the shared copy alone carries
    correction: dict[str, Any] | None = None
    if invalid is None and task.correction is not None and position == int(task.correction["after_session"]) + 1:
        try:
            correction = corrections.deliver(
                arm.name,
                task.correction,
                dirs.workspace,
                dirs.memory_dir,
                _ops(arm, dirs, chain_id, cfg) if arm.persist_store else None,
                _cli(arm, dirs, chain_id, cfg) if arm.wiki_governed else None,
            )
        except corrections.CorrectionError as exc:
            correction = {"path": corrections.PATHS[arm.name], "delivered": False, "error": str(exc)}
            invalid = "correction_failed"
    ledger = dirs.root / "hook-ledger.jsonl"
    if invalid is None:
        wiring = _write_wiring(arm, dirs, chain_id, cfg, ledger, task.brief_for(position))
        if cfg.agent_uid is not None:  # the session's files are the agent's while it runs, and only then
            _own(dirs.root, cfg.agent_uid, cfg.agent_gid if cfg.agent_gid is not None else cfg.agent_uid, 0o700)
        env = _session_env(arm, dirs, chain_id, cfg)
        session_uuid = str(uuid.uuid4())
        raw = dirs.root / STREAM_FILE
        for index, step in enumerate(session.steps):
            if step.stage == "exposure":
                exposure_at = utc_now()
            elif step.stage == "evaluation":
                evaluation_at = utc_now()
            prompts.append(step.prompt)
            resume = ["--session-id", session_uuid] if index == 0 else ["--resume", session_uuid]
            cmd = [
                *cfg.agent_cmd,
                "-p",
                step.prompt,
                "--output-format",
                "stream-json",
                "--verbose",
                "--model",
                cfg.model,
                "--permission-mode",
                "acceptEdits",
                "--allowed-tools",
                ",".join(arm.allowed_tools),
                *resume,
                *wiring,
            ]
            result = _run_step(cmd, dirs.workspace, env, cfg.timeout_s, raw)
            summarise(result.lines, into=summary)
            if result.spawn_failed or (index == 0 and not summary.init_seen):
                invalid = "session_not_started"
                break
            if summary.authentication_failed:  # the API refused the run's key, at any step (FR-015a (c))
                invalid = "authentication_failed"
                break
            if index == 0 and arm.mcp and summary.mcp_status.get("memkernel") not in CONNECTED_STATUSES:
                invalid = "mcp_not_connected"
                break
            if result.timed_out:
                timed_out = True
                break
        hooks = _read_ledger(ledger)
    if cfg.agent_uid not in (None, os.geteuid()) and invalid != "fixture_restore_failed":
        kill_user_processes(cfg.agent_uid)  # no agent process (a detached child, a daemon) outlives its session
    ran_in = dirs.workspace  # the path the agent saw: tool calls in the stream name it
    if dirs is not home:
        if cfg.agent_uid is not None:
            _own(dirs.root, os.geteuid(), os.getegid(), 0o700)
        unstage_session(dirs, home)
        dirs = home
    compacted = any(
        exposure_at is not None and evaluation_at is not None and exposure_at < ts < evaluation_at
        for ts in summary.compactions
    )
    if invalid is None and task.group == "lc-compact" and evaluation_at is not None and not compacted:
        invalid = "no_compaction_before_evaluation"

    stage = "exposure" if position == 0 else ("evaluation" if position == len(task.sessions) - 1 else "intermediate")
    if len(task.sessions) == 1:
        stage = "evaluation"
    receipt: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "run_id": cfg.run_id,
        "phase": cfg.phase,
        "chain_id": chain_id,
        "position": position,
        "chain_length": len(task.sessions),
        "stage": stage,
        "namespace_sha256": sha256_text(chain_id + "/" + session.namespace),
        "arm": arm.name,
        "task_id": task.task_id,
        "group": task.group,
        "run_index": run_index,
        "started_at": started_at,
        "ended_at": utc_now(),
        "model": cfg.model,
        "code_sha": cfg.code_sha,
        "arm_config_sha256": arm.config_sha256,
        "preregistration_sha256": cfg.preregistration_sha256,
        "valid": invalid is None,
        "invalid_reason": invalid,
        "outcome": None,
        "checker_passed": None,
        "hooks": hooks,
        "tool_calls": tool_counts(summary),
        "tokens": summary.tokens,
        "compaction_tokens_estimate": summary.compaction_tokens_estimate,
        "compaction_estimates_missing": summary.compaction_estimates_missing,
        "api_errors": dict(sorted(summary.api_errors.items())),
        "wall_time_ms": int((time.monotonic() - t0) * 1000),
        "stages": {"exposure_at": exposure_at, "evaluation_at": evaluation_at, "compactions": summary.compactions},
        "diagnostics": session_diagnostics(summary, ran_in, earlier_reads, hooks),
        "answer_class": None,  # lc-correct only: informed, obsolete or other (FR-001), set by grading
        "correction": correction,  # lc-correct only: what the arm's correction event did (FR-002)
        "gate": None,  # the governed arms' evaluation session: the end state against the gate's records (FR-004)
        "hashes": {
            "prompt": sha256_text("\n".join(prompts)),
            "response": sha256_text(summary.response),
            "tool_payloads": tool_payload_digest(summary),
        },
    }
    if timed_out and receipt["valid"]:
        receipt["outcome"] = "timeout"  # a valid failure of this session; the chain inherits it (FR-015a)
    return SessionOutcome(receipt, summary, dirs, prompts, timed_out, ran_in)


# ── grading ───────────────────────────────────────────────────


def _load_checker(task: Task) -> Any:
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        f"lc_checker_{task.task_id.replace('-', '_')}", task.root / "checker.py"
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"no checker for {task.task_id}")
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(SUITE_DIR))
    spec.loader.exec_module(module)
    return module


def grade(task: Task, arm: Arm, final: SessionOutcome, cfg: RunConfig, earlier_timeout: bool = False) -> None:
    """Fill outcome fields on the evaluation session's receipt (FR-015a: failures stay failures).

    A timeout in any session of the chain makes the trial a timeout, even when
    the evaluation session itself finished and its checker would pass.
    """
    receipt = final.receipt
    if not receipt["valid"]:
        return
    if final.timed_out or earlier_timeout:
        receipt["outcome"] = "timeout"
        return
    try:
        checker = _load_checker(task)
        passed, _detail = checker.check(final.dirs.workspace, task.oracle_dir(cfg.oracles_root))
        if hasattr(checker, "classify"):  # lc-correct's three outcomes (FR-001)
            receipt["answer_class"] = checker.classify(final.dirs.workspace, task.oracle_dir(cfg.oracles_root))
    except Exception:  # a crashing checker is a harness failure, never the agent's
        receipt["valid"], receipt["invalid_reason"] = False, "checker_crashed"
        return
    receipt["checker_passed"] = bool(passed)
    required = [h for h in arm.hooks if h in ("PreCompact", "PostCompact")] if task.group == "lc-compact" else []
    # Every execution of a required hook must succeed; one success never masks a failed run (FR-015a).
    hooks_ok = all(
        any(h["event"] == name for h in receipt["hooks"])
        and all(h["exit_status"] == 0 for h in receipt["hooks"] if h["event"] == name)
        for name in required
    )
    if passed and hooks_ok:
        receipt["outcome"] = "passed"
    elif not passed and not final.summary.response.strip():
        receipt["outcome"] = "no_answer"
    else:
        receipt["outcome"] = "failed"


# ── chains and runs ───────────────────────────────────────────


def run_chain(task: Task, arm: Arm, run_index: int, cfg: RunConfig, observe: Any = None) -> list[dict[str, Any]]:
    chain_dir = chain_dir_for(task, arm, run_index, cfg)
    chain_dir.mkdir(parents=True, mode=0o700)  # the harness's: the agent never reads another chain, or its own
    state = ChainState()
    earlier_reads: set[str] = set()
    receipts: list[dict[str, Any]] = []
    outcome: SessionOutcome | None = None
    for position in range(len(task.sessions)):
        outcome = run_session(task, arm, run_index, position, chain_dir, state, earlier_reads, cfg, observe)
        receipts.append(outcome.receipt)
        if not outcome.receipt["valid"]:
            break
        earlier_reads |= set(read_paths(outcome.summary, outcome.ran_in or outcome.dirs.workspace))
        transcript = chain_dir / f"transcript-{position}.md"
        transcript.write_text(render_transcript(outcome.prompts, outcome.summary), encoding="utf-8")
        state = ChainState(workspace=outcome.dirs.workspace, transcripts=[*state.transcripts, transcript])
    # Calibration is never graded: nobody sees pass/fail before the preregistration is committed, so its
    # receipts carry usage and stream evidence only. Measured and demo runs are graded exactly as before.
    # lc-correct is the exception (memkernel-0-16 FR-003, decision B3): its calibration grades bare and the informed
    # reference only, to qualify each chain; no measured arm runs in it, so nothing about them is seen early.
    gradeable = cfg.phase != CALIBRATION_PHASE or task.group == CORRECT_GROUP
    final_ok = outcome is not None and outcome.receipt["valid"] and outcome.receipt["stage"] == "evaluation"
    if arm.wiki_governed and final_ok and outcome is not None:  # first: a check that cannot run voids the trial
        check_gate(task, arm, outcome, chain_dir.name, cfg)
    if gradeable and final_ok and outcome is not None and outcome.receipt["valid"]:
        earlier_timeout = any(r["outcome"] == "timeout" for r in receipts[:-1])
        grade(task, arm, outcome, cfg, earlier_timeout=earlier_timeout)
    for receipt in receipts:
        errors = validate_receipt(receipt)
        if errors:
            raise ValueError(f"receipt does not match the schema: {errors}")
    return receipts


def check_gate(task: Task, arm: Arm, final: SessionOutcome, chain_id: str, cfg: RunConfig) -> None:
    """#90 section 3.4 on the governed arms' end state: breaches are counted in the receipt, never hidden."""
    workspace = final.dirs.workspace
    try:
        final.receipt["gate"] = _ops(arm, final.dirs, chain_id, cfg)(
            "gate",
            "--root",
            str(workspace),
            "--wiki",
            str(workspace / WIKI_DIR),
            "--proposals",
            str(workspace / GOVERNED_PROPOSALS_DIR),
            "--fixture-wiki",
            str(task.tree / WIKI_DIR),
        )
    except corrections.CorrectionError as exc:  # the check could not run: a harness failure, not the arm's
        final.receipt["gate"] = {**GATE_UNCHECKED, "error": str(exc)}
        final.receipt["valid"], final.receipt["invalid_reason"] = False, "gate_check_failed"


def chain_dir_for(task: Task, arm: Arm, run_index: int, cfg: RunConfig) -> Path:
    return cfg.run_root / cfg.run_id / f"{task.task_id}.{arm.name}.r{run_index}"


_DIR_NOFOLLOW = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW


def discard_session_state(chain_dir: Path) -> None:
    """Delete what a calibration chain's agent left behind: ungraded calibration with workspace cleanup.

    Workspaces, homes, Claude Code config directories (which hold its own session
    files), stores and transcripts all go; each session's ``stream.jsonl`` stays,
    because FR-018 keeps raw streams for wiring review and the secret scan. This is
    not blinding: the stream still records the agent's edits and responses, so
    reading it can reveal an outcome. Called only after the chain's receipts are on
    disk.

    Traversal is by directory descriptor, opened with ``O_NOFOLLOW`` from the chain
    root down, and every removal is relative to the descriptor it was found under,
    so a symlink at any level, the root included, is never followed even if a
    process the agent left running swaps a directory for a link mid-cleanup.
    """
    if not shutil.rmtree.avoids_symlink_attacks:
        raise OSError("this platform's shutil.rmtree is not safe against symlink attacks; refusing to clean up")
    try:
        root_fd = os.open(chain_dir, _DIR_NOFOLLOW)
    except OSError as exc:  # ELOOP / ENOTDIR: the root is a link or not a directory
        raise OSError(f"refusing to clean {chain_dir}: not a real directory ({exc})") from exc
    try:
        with os.scandir(root_fd) as entries:
            names = [(entry.name, entry.is_dir(follow_symlinks=False)) for entry in entries]
        for name, is_dir in names:
            if is_dir and name.startswith("s") and name[1:].isdigit():
                _clean_session(name, root_fd)
            else:
                _remove_entry(name, is_dir, root_fd)
    finally:
        os.close(root_fd)


def _clean_session(name: str, parent_fd: int) -> None:
    session_fd = os.open(name, _DIR_NOFOLLOW, dir_fd=parent_fd)
    try:
        with os.scandir(session_fd) as entries:
            items = [
                (entry.name, entry.is_dir(follow_symlinks=False), entry.is_file(follow_symlinks=False))
                for entry in entries
            ]
        for item, is_dir, is_file in items:
            if item == STREAM_FILE and is_file:
                continue
            _remove_entry(item, is_dir, session_fd)
    finally:
        os.close(session_fd)


def _remove_entry(name: str, is_dir: bool, parent_fd: int) -> None:
    """Remove ``name`` under ``parent_fd``; a directory replaced by a link since the scan makes rmtree refuse."""
    if is_dir:
        shutil.rmtree(name, dir_fd=parent_fd)
    else:
        os.unlink(name, dir_fd=parent_fd)


def _inside_checkout(path: Path) -> bool:
    probe = path if path.exists() else path.parent
    completed = subprocess.run(
        ["git", "-C", str(probe), "rev-parse", "--is-inside-work-tree"], capture_output=True, text=True, check=False
    )
    return completed.returncode == 0 and completed.stdout.strip() == "true"


def check_cli_pin(arm: Arm, executable: str | None = None) -> None:
    """Refuse a paid run unless ``arm``'s pinned command reports its pinned version: the command on the session
    PATH, or ``executable``, the exact file the runner itself will invoke (the governed arms' curator CLI)."""
    if arm.cli_pin is None:
        return
    command, version = arm.cli_pin
    command = executable or command
    env = {key: os.environ[key] for key in ENV_PASSTHROUGH if key in os.environ and key != "ANTHROPIC_API_KEY"}
    try:
        completed = subprocess.run(
            [command, "--version"], capture_output=True, text=True, env=env, timeout=30, check=False
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SystemExit(
            f"{arm.name}: `{command} --version` could not run ({exc}); install {command}=={version}"
        ) from exc
    reported = completed.stdout.strip().split()[-1:] if completed.returncode == 0 else []
    if reported != [version]:
        found = completed.stdout.strip() or completed.stderr.strip() or f"exit {completed.returncode}"
        raise SystemExit(f"{arm.name}: `{command} --version` reports {found!r}, the arm is frozen at {version}")


AGENT_USER, GRADER_USER = "agent", "grader"  # the image's unprivileged users (calibration/Dockerfile)


def require_isolated_image(cfg: RunConfig) -> None:
    """Refuse a calibration or measured run outside the isolated image (the #90 review).

    It starts only as root, with the image's ``agent`` and ``grader`` users present and named by the run
    (``--agent-uid``, ``LC_GRADER_UID``), and with the repository, the tasks and the oracles unreadable to ``agent``:
    checked by a read attempt made as that user, not inferred from file modes.
    """
    import pwd

    from checker_support import GRADER_UID_ENV

    problems: list[str] = []
    if os.geteuid() != 0:
        problems.append("the harness is not root")
    users = {}
    for name in (AGENT_USER, GRADER_USER):
        try:
            users[name] = pwd.getpwnam(name)
        except KeyError:
            problems.append(f"there is no {name} user")
    agent, grader = users.get(AGENT_USER), users.get(GRADER_USER)
    if agent is not None and cfg.agent_uid != agent.pw_uid:
        problems.append(f"--agent-uid is {cfg.agent_uid}, not the agent user's {agent.pw_uid}")
    if grader is not None and os.environ.get(GRADER_UID_ENV) != str(grader.pw_uid):
        problems.append(
            f"{GRADER_UID_ENV} is {os.environ.get(GRADER_UID_ENV)!r}, not the grader user's {grader.pw_uid}"
        )
    if agent is not None and os.geteuid() == 0:
        for path in dict.fromkeys((REPO_ROOT, cfg.tasks_root, cfg.oracles_root)):
            readable = subprocess.run(
                ["setpriv", f"--reuid={agent.pw_uid}", f"--regid={agent.pw_gid}", "--clear-groups", "--", "test",
                 "-r", str(path)],
                capture_output=True,
                check=False,
            )  # fmt: skip
            if readable.returncode == 0:
                problems.append(f"the agent user can read {path}")
    if problems:
        raise SystemExit(f"a {cfg.phase} run starts only in the isolated image: {'; '.join(problems)}")


def resolve_curator_cli(command: str) -> str:
    """The absolute path of the curator CLI: a paid run version-checks this file and invokes only it, so a later
    PATH lookup can never run another binary than the one the pin was checked against."""
    found = shutil.which(command)
    if found is None:
        raise SystemExit(f"the curator CLI {command!r} is not on PATH")
    return str(Path(found).resolve())


def refuse_misplaced_arms(phase: str, tasks: list[Task], arms: list[Arm]) -> None:
    """An arm outside its phases never runs (``informed`` is calibration-only), and an lc-correct calibration runs
    only bare and the informed reference, so no measured arm is graded before the preregistration (FR-003)."""
    for arm in arms:
        if arm.phases and phase not in arm.phases and phase != "demo":
            raise SystemExit(f"{arm.name} runs only in {', '.join(arm.phases)}, not in a {phase} run")
    if phase == CALIBRATION_PHASE and any(t.group == CORRECT_GROUP for t in tasks):
        extra = [a.name for a in arms if a.name not in CORRECT_CALIBRATION_ARMS]
        if extra:
            raise SystemExit(
                f"an {CORRECT_GROUP} calibration runs only {', '.join(CORRECT_CALIBRATION_ARMS)}; "
                f"remove {', '.join(extra)}"
            )


def run(cfg: RunConfig, task_ids: list[str], arm_names: list[str], runs: int, observe: Any = None) -> Path:
    """Run every chain of ``task_ids`` × ``arm_names`` × ``runs`` and write the receipts under the run root.

    The CLI refuses a calibration or measured phase without ``--shared-cache``; callers outside the CLI must pass
    a shared cache for those phases themselves, or the memkernel server goes online for its embedding model.
    """
    if cfg.agent_uid is not None and os.geteuid() not in (0, cfg.agent_uid):
        raise SystemExit("--agent-uid needs the harness to run as root: it hands each session to that user and back")
    if _inside_checkout(cfg.run_root):
        raise SystemExit(f"refusing to run inside a git checkout: {cfg.run_root}")
    out = cfg.run_root / cfg.run_id
    if out.exists() and any(out.iterdir()):
        raise SystemExit(f"run directory is not empty: {out}")
    tasks = [load_task(cfg.tasks_root / task_id) for task_id in task_ids]
    arms = [load_arm(name) for name in arm_names]
    refuse_misplaced_arms(cfg.phase, tasks, arms)
    if cfg.phase in (CALIBRATION_PHASE, MEASURED_PHASE):  # every check before anything is created or spent
        require_isolated_image(cfg)
        if any(arm.wiki_governed for arm in arms):
            cfg = replace(cfg, wiki_studio_cmd=resolve_curator_cli(cfg.wiki_studio_cmd))
        for arm in arms:  # the governed arms' pin is checked on the curator executable the runner invokes
            if arm.wiki_governed:
                check_cli_pin(arm, cfg.wiki_studio_cmd)
            else:
                check_cli_pin(arm)
    out.mkdir(parents=True, exist_ok=True)
    if cfg.agent_uid is not None:  # the agent may pass through to its session, never list the run (chain names)
        os.chmod(out, 0o711)
    receipts_path = out / "receipts.jsonl"
    receipts_fd = os.open(receipts_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)  # never the agent's to read
    with open(receipts_fd, "w", encoding="utf-8") as sink:
        for run_index in range(runs):
            for task in tasks:
                for arm in arms:
                    if not arm.runs_on(task):  # e.g. wiki_studio outside lc-wiki: no chain, no receipt
                        continue
                    for receipt in run_chain(task, arm, run_index, cfg, observe):
                        sink.write(json.dumps(receipt, sort_keys=True) + "\n")
                    sink.flush()
                    os.fsync(sink.fileno())
                    if cfg.phase == CALIBRATION_PHASE:  # receipts are durable before anything is deleted
                        chain_dir = chain_dir_for(task, arm, run_index, cfg)
                        try:
                            discard_session_state(chain_dir)
                        except OSError as exc:
                            raise SystemExit(
                                f"calibration cleanup failed in {chain_dir}: {exc}; the receipts written so far "
                                f"are in {receipts_path}; remove what is left of that chain by hand, then rerun "
                                "the remaining chains under a new run id"
                            ) from exc
    return receipts_path


# ── demo (FR-014) ─────────────────────────────────────────────

DEMO_TASKS = ("demo-retain", "demo-wiki", "demo-compact", "demo-correct")
CORRECTION_FILES = {  # where a file-based correction path leaves the brief (memkernel-0-16 FR-002)
    "claude_md": ("workspace", corrections.CLAUDE_MD_FILE),
    "fs_grep": ("memory", corrections.GREP_NOTE_FILE),
}


def demo() -> int:
    """Run three scripted tasks for every arm with the stub agent and check each frozen rule."""
    seen: dict[tuple[str, str, int], dict[str, bool]] = {}

    def observe(task: Task, arm: Arm, position: int, dirs: SessionDirs) -> None:
        store_files = list(dirs.store.iterdir()) if dirs.store is not None else []
        seen[(task.task_id, arm.name, position)] = {
            "workspace_note": (dirs.workspace / "NOTES.md").exists(),
            "transcripts": bool(dirs.memory_dir and any(dirs.memory_dir.iterdir())),
            "store_marker": any(p.name == "stub-store-marker" for p in store_files),
            "wiki_page": (dirs.workspace / "knowledge" / "wiki" / "decisions" / "demo.md").exists(),
            # lc-correct: observed before the correction, so this is what the shared copy alone carries (SC-2)
            "shared_copy_has_y": task.correction is not None
            and position > 0
            and any(
                term.lower() in p.read_text(encoding="utf-8", errors="replace").lower()
                for p in (dirs.workspace / (task.shared_artifact or "")).rglob("*")
                if p.is_file()
                for term in _fact_terms(task)
            ),
        }

    # In the image, run.sh sets these: the stub agent then runs as the agent user from a world-readable copy, and
    # its probe must find nothing of the run, the other sessions or the oracles (the #90 review's blinding check).
    uid = int(os.environ["LC_AGENT_UID"]) if os.environ.get("LC_AGENT_UID") else None
    gid = int(os.environ.get("LC_AGENT_GID") or uid) if uid is not None else None
    tools = Path(os.environ.get("LC_AGENT_TOOLS") or SUITE_DIR)
    agent: tuple[str, ...] = (sys.executable, str(tools / "stub_agent.py"))
    if uid is not None:
        agent = ("setpriv", f"--reuid={uid}", f"--regid={gid}", "--clear-groups", "--", *agent)
    # In the image, run.sh also sets these: the memkernel arm's real hooks then run, as the agent, from the agent
    # tools, against the image's pinned model cache (the #90 review: hooks work as the agent user).
    hooks_python = os.environ.get("LC_DEMO_HOOKS_PYTHON")
    shared_cache = Path(os.environ["LC_SHARED_CACHE"]) if os.environ.get("LC_SHARED_CACHE") else None
    hooks_dir = tools if (tools / HOOK_SCRIPTS["SessionStart"]).is_file() else REPO_ROOT / "templates" / "hooks"
    curator_cli = _wiki_studio_beside_python()
    arms = list(ARM_NAMES)
    if not _curator_cli_usable(curator_cli):
        arms = [a for a in arms if not load_arm(a).wiki_governed]
        print(f"demo: {curator_cli} predates wiki-studio 0.7 (no approve), so the governed arms are left out")
    with tempfile.TemporaryDirectory() as tmp:
        if uid is not None:
            os.chmod(tmp, 0o711)  # the agent passes through to its session; it may list nothing on the way
        cfg = RunConfig(
            run_root=Path(tmp),
            run_id="demo",
            phase="demo",
            model="stub",
            code_sha="demo",
            preregistration_sha256=None,
            agent_cmd=agent,
            ledger_script=tools / "hook_ledger.py",
            agent_uid=uid,
            agent_gid=gid,
            memkernel_cmd="stub-memkernel",
            memkernel_python=hooks_python or sys.executable,
            tasks_root=SUITE_DIR / "fixtures" / "demo-tasks",
            oracles_root=SUITE_DIR / "fixtures" / "demo-oracles",
            timeout_s=300.0 if hooks_python else 60.0,
            hook_command_override=None if hooks_python else (sys.executable, "-c", "import sys; sys.stdin.read()"),
            hooks_dir=hooks_dir,
            shared_cache=shared_cache,
            ops_command=(sys.executable, str(SUITE_DIR / "stub_ops.py")),
            wiki_studio_cmd=_wiki_studio_beside_python(),
        )
        receipts_path = run(cfg, list(DEMO_TASKS), arms, runs=1, observe=observe)
        receipts = [json.loads(line) for line in receipts_path.read_text(encoding="utf-8").splitlines()]
        delivered = _delivered_files(Path(tmp) / "demo")
        probes = _probes(Path(tmp) / "demo", arms)
        grading = _grading_probe(Path(tmp))

    # the evidence first: check_lingering kills what survived, which would hide it
    seen_lines = evidence(probes, grading, receipts, separated=uid is not None, real_hooks=bool(hooks_python))
    failures = check_demo(seen, receipts, delivered, arms) + check_probes(probes, separated=uid is not None)
    failures += check_lingering(probes, separated=uid is not None)
    failures += check_grading(grading, separated=uid is not None)
    if hooks_python:
        failures += check_real_hooks(receipts)
    for line in seen_lines:
        print(line)
    for line in failures:
        print(f"FAIL {line}")
    print(f"demo: {len(receipts)} receipts, {len(seen)} sessions observed, {len(failures)} failure(s)")
    return 1 if failures else 0


def _fact_terms(task: Task) -> list[str]:
    terms: list[str] = json.loads((task.root / "task.json").read_text(encoding="utf-8")).get("fact_terms", [])
    return terms


def _wiki_studio_beside_python() -> str:
    """The wiki-studio installed beside this Python (the dev environment's), else whatever is on PATH."""
    beside = Path(sys.executable).with_name("wiki-studio")
    return str(beside) if beside.exists() else "wiki-studio"


def _curator_cli_usable(command: str) -> bool:
    """Whether ``command`` is a wiki-studio with ``approve`` (0.7 or later), which the governed arms' curator needs."""
    try:
        out = subprocess.run([command, "--version"], capture_output=True, text=True, timeout=30, check=False).stdout
    except (OSError, subprocess.TimeoutExpired):
        return False
    numbers = [int(n) for n in re.findall(r"\d+", out.strip().split()[-1])[:2]] if out.strip() else []
    return len(numbers) == 2 and tuple(numbers) >= (0, 7)


def _probes(run_dir: Path, arms: list[str]) -> dict[str, dict[str, Any] | None]:
    """Each arm's PROBE.json from its demo-correct evaluation session, as the chain keeps it."""
    found: dict[str, dict[str, Any] | None] = {}
    task = load_task(SUITE_DIR / "fixtures" / "demo-tasks" / "demo-correct")
    for arm in (a for a in arms if load_arm(a).runs_on(task)):
        path = run_dir / f"demo-correct.{arm}.r0" / "s1" / "workspace" / "PROBE.json"
        found[arm] = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
    return found


def _unreadable(value: object) -> bool:
    return isinstance(value, str) and value.startswith("unreadable")


def check_probes(probes: dict[str, dict[str, Any] | None], separated: bool) -> list[str]:
    """The blinding checks of the #90 review, from what the stub agent could reach in its evaluation session.

    Always: its working directory names neither the task nor the arm, the sessions folder holds its own session
    only, and session 0 of its chain is not at ``../../s0``. With the agent running as its own user (the image):
    the run directory cannot be listed, and the oracles cannot be read.
    """
    failures: list[str] = []
    for arm, found in probes.items():
        if found is None:
            failures.append(f"{arm}: the evaluation session left no PROBE.json")
            continue
        cwd = Path(str(found["cwd"]))
        if "demo-correct" in str(cwd) or f".{arm}." in str(cwd) or arm in cwd.parts:
            failures.append(f"{arm}: the working directory {cwd} names the task or the arm")
        # its own session only; in the image the agent cannot list the sessions folder at all, which is stronger
        if found["sessions"] != [cwd.parent.name] and not (separated and _unreadable(found["sessions"])):
            failures.append(f"{arm}: the sessions folder shows {found['sessions']!r}, not only its own session")
        if found["s0_reachable"]:
            failures.append(f"{arm}: session 0 of the chain is reachable at ../../s0")
        if separated and not _unreadable(found["run_dir"]):
            failures.append(f"{arm}: the agent can list the run directory: {found['run_dir']!r}")
        if separated and not _unreadable(found["oracles"]):
            failures.append(f"{arm}: the agent can read the image's oracles: {found['oracles']!r}")
    return failures


def _alive(pid: int) -> bool:
    """Whether ``pid`` is a running process (a zombie, killed but not yet reaped, is not)."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    stat = Path(f"/proc/{pid}/stat")
    try:
        return stat.read_text().rsplit(")", 1)[1].split()[0] != "Z"
    except (OSError, IndexError):
        return True


def check_lingering(probes: dict[str, dict[str, Any] | None], separated: bool) -> list[str]:
    """No agent process survives its session (the #90 review). The probe left one process in the session's process
    group and one detached from it: the runner kills the group after each step, and in the image every process of
    the agent user after each session. Outside the image (no agent user) a detached process can escape, so it is
    killed here and not counted."""
    failures: list[str] = []
    for arm, found in probes.items():
        lingering = (found or {}).get("lingering") or {}
        for kind, pid in lingering.items():
            if _alive(int(pid)):
                if separated or kind == "in_group":
                    failures.append(f"{arm}: the probe's {kind} process {pid} survived the session")
                with contextlib.suppress(ProcessLookupError, PermissionError):
                    os.kill(int(pid), signal.SIGKILL)
    return failures


GRADING_PROBE = SUITE_DIR / "fixtures" / "demo-oracles" / "grading-probe"


def _grading_probe(tmp: Path) -> tuple[bool, str]:
    """Grade an empty workspace with a driver that reports the uid the candidate's code runs as."""
    from checker_support import run_driver

    workspace = tmp / "grading-probe"
    workspace.mkdir()
    return run_driver(workspace, GRADING_PROBE)


def check_grading(result: tuple[bool, str], separated: bool) -> list[str]:
    """Grading runs the candidate's code as an unprivileged user, never as root (the #90 review)."""
    from checker_support import grader_ids

    _, verdict = result
    expected = grader_ids() if separated else None
    want = f"uid {expected[0]}" if expected is not None else f"uid {os.geteuid()}"
    failures = [] if verdict == want else [f"grading ran the candidate's code as {verdict!r}, expected {want!r}"]
    if separated and verdict == "uid 0":
        failures.append("grading ran the candidate's code as root")
    return failures


def evidence(
    probes: dict[str, dict[str, Any] | None],
    grading: tuple[bool, str],
    receipts: list[dict[str, Any]],
    separated: bool,
    real_hooks: bool,
) -> list[str]:
    """What the blinding, process, grading and hook checks saw, printed whether they pass or fail."""
    found = [p for p in probes.values() if p is not None]

    def values(key: str) -> str:
        return ", ".join(sorted({str(p[key]) if not isinstance(p[key], list) else "listed" for p in found}))

    hooks = [h for r in receipts for h in r["hooks"]]
    return [
        f"evidence: agent user {'separate' if separated else 'the harness itself'}; probes from {len(found)} arms",
        f"evidence: sessions folder: {values('sessions')}; run folder: {values('run_dir')}; "
        f"oracles: {values('oracles')}",
        f"evidence: ../../s0 reachable: {values('s0_reachable')}; working directories: "
        + ", ".join(sorted({str(Path(str(p["cwd"])).parent.parent.name) for p in found})),
        f"evidence: lingering processes alive after their sessions: "
        f"{sum(_alive(int(pid)) for p in found for pid in (p.get('lingering') or {}).values())} of "
        f"{sum(len(p.get('lingering') or {}) for p in found)}",
        f"evidence: grading probe: {grading[1]}",
        f"evidence: hooks ({'real scripts' if real_hooks else 'stub'}): {len(hooks)} runs, exit statuses "
        + ", ".join(f"{s}: {n}" for s, n in sorted(Counter(h["exit_status"] for h in hooks).items())),
    ]


def check_real_hooks(receipts: list[dict[str, Any]]) -> list[str]:
    """With the real hook scripts, every hook the agent user ran exited 0, and the memkernel arm ran them all."""
    failures = [
        f"{r['chain_id']} s{r['position']}: hook {h['event']} exited {h['exit_status']}"
        for r in receipts
        for h in r["hooks"]
        if h["exit_status"] != 0
    ]
    events = {h["event"] for r in receipts if r["arm"] == "memkernel" for h in r["hooks"]}
    if not {"SessionStart", "PreCompact", "PostCompact"} <= events:
        failures.append(f"memkernel: the real hooks ran only {sorted(events)}")
    return failures


def _delivered_files(run_dir: Path) -> dict[str, bool]:
    """For each file-based correction path, whether the evaluation session started with the brief in its file."""
    found: dict[str, bool] = {}
    for arm_name, (where, name) in CORRECTION_FILES.items():
        chain = run_dir / f"demo-correct.{arm_name}.r0"
        target = chain / "s1" / "workspace" / name if where == "workspace" else chain / "memory" / name
        found[arm_name] = target.is_file() and "DEMO-Y" in target.read_text(encoding="utf-8")
    return found


def check_demo(
    seen: dict[tuple[str, str, int], dict[str, bool]],
    receipts: list[dict[str, Any]],
    delivered: dict[str, bool] | None = None,
    arms: list[str] | None = None,
) -> list[str]:
    failures: list[str] = []
    rules = {arm: load_arm(arm) for arm in (arms if arms is not None else ARM_NAMES)}  # the arms the demo ran
    demo_tasks = {task_id: load_task(SUITE_DIR / "fixtures" / "demo-tasks" / task_id) for task_id in DEMO_TASKS}
    for arm_name, arm in rules.items():
        for task_id, task in demo_tasks.items():
            ran = any(key[:2] == (task_id, arm_name) for key in seen)
            if ran != arm.runs_on(task):
                verb, rule = ("ran", "exclude") if ran else ("did not run", "include")
                failures.append(f"{arm_name}: {verb} on {task_id}, but its groups {rule} {task.group}")
        if ("demo-retain", arm_name, 1) not in seen:
            continue
        retain = seen[("demo-retain", arm_name, 1)]
        if retain["workspace_note"] != arm.persist_workspace:
            failures.append(
                f"{arm_name}: workspace carry-over {retain['workspace_note']} != rule {arm.persist_workspace}"
            )
        if retain["transcripts"] != arm.persist_transcripts:
            failures.append(
                f"{arm_name}: transcript carry-over {retain['transcripts']} != rule {arm.persist_transcripts}"
            )
        if retain["store_marker"] != arm.persist_store:
            failures.append(f"{arm_name}: store carry-over {retain['store_marker']} != rule {arm.persist_store}")
    for arm_name in rules:
        if ("demo-wiki", arm_name, 1) not in seen:
            continue
        wiki = seen[("demo-wiki", arm_name, 1)]
        if not wiki["wiki_page"]:
            failures.append(f"{arm_name}: the lc-wiki shared artifact did not reach the destination session")
        if wiki["store_marker"]:
            failures.append(f"{arm_name}: the destination namespace's store is not empty")
    for receipt in receipts:
        if receipt["task_id"] == "demo-compact":
            if not receipt["valid"]:
                failures.append(f"{receipt['arm']}: compact demo invalid ({receipt['invalid_reason']})")
            events = [h["event"] for h in receipt["hooks"]]
            if receipt["arm"] == "memkernel" and not {"PreCompact", "PostCompact"} <= set(events):
                failures.append(f"memkernel: hook events not recorded around the simulated compaction: {events}")
        if receipt["stage"] == "evaluation" and receipt["valid"] and receipt["outcome"] is None:
            failures.append(f"{receipt['chain_id']}: evaluation session was not graded")
        if receipt["task_id"] == "demo-correct" and receipt["position"] == 1:
            failures += _check_demo_correction(receipt)
    for key, observed in seen.items():
        if observed.get("shared_copy_has_y"):
            failures.append(f"{key[1]}: the shared copy carried the correction into session {key[2]}")
    for arm_name, ok in (delivered or {}).items():
        if not ok:
            failures.append(f"{arm_name}: the curator's correction is not in its file at the evaluation session")
    return failures


def _check_demo_correction(receipt: dict[str, Any]) -> list[str]:
    """SC-2: each arm's correction went through its own path, and only there."""
    arm, record = receipt["arm"], receipt["correction"]
    if not receipt["valid"]:
        return [f"{arm}: the corrected session is invalid ({receipt['invalid_reason']})"]
    if record is None or record["path"] != corrections.PATHS[arm]:
        return [f"{arm}: correction path {record and record['path']!r}, expected {corrections.PATHS[arm]!r}"]
    expected = {  # the stub agent exports no draft, so the scripted curator refuses and the oracle lands its page
        corrections.NONE: False,
        corrections.SCRIPTED: False,
        corrections.ORACLE: True,
    }.get(record["path"], True)
    if record["delivered"] is not expected:
        return [f"{arm}: correction delivered={record['delivered']}, expected {expected}"]
    if record["path"] in (corrections.SCRIPTED, corrections.ORACLE) and receipt["gate"] is None:
        return [f"{arm}: no gate check on the governed arm's end state"]
    return []


# ── CLI ───────────────────────────────────────────────────────


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("demo")
    p_run = sub.add_parser("run")
    p_run.add_argument("--tasks-root", type=Path, default=SUITE_DIR / "tasks")
    p_run.add_argument("--oracles-root", type=Path, default=SUITE_DIR / "oracles")
    p_run.add_argument("--task", action="append", required=True)
    p_run.add_argument("--arm", action="append", choices=ARM_NAMES, required=True)
    p_run.add_argument("--runs", type=int, default=1)
    p_run.add_argument("--run-root", type=Path, required=True)
    p_run.add_argument("--run-id", required=True)
    p_run.add_argument("--phase", choices=(CALIBRATION_PHASE, MEASURED_PHASE), required=True)
    p_run.add_argument("--model", required=True)
    p_run.add_argument("--code-sha", required=True)
    p_run.add_argument("--preregistration", type=Path)
    p_run.add_argument("--memkernel-cmd", required=True)
    p_run.add_argument("--memkernel-python", required=True)
    p_run.add_argument("--agent-cmd", default="claude")
    p_run.add_argument("--timeout", type=float, default=900.0)
    p_run.add_argument("--shared-cache", type=Path)
    p_run.add_argument("--wiki-studio-cmd", default="wiki-studio", help="the governed arms' curator CLI")
    p_run.add_argument("--agent-uid", type=int, help="run each session's files as this user (the image's agent)")
    p_run.add_argument("--agent-gid", type=int)
    p_run.add_argument("--hooks-dir", type=Path, default=REPO_ROOT / "templates" / "hooks")
    p_run.add_argument("--ledger-script", type=Path, default=SUITE_DIR / "hook_ledger.py")
    args = parser.parse_args(argv)
    if args.command == "demo":
        return demo()
    if args.phase == MEASURED_PHASE and args.preregistration is None:
        parser.error("a measured run needs --preregistration")
    if args.shared_cache is None:  # without it the memkernel server would go online for its model (HF_HUB_OFFLINE)
        parser.error(f"a {args.phase} run needs --shared-cache (the image's pinned model cache)")
    cfg = RunConfig(
        run_root=args.run_root.resolve(),
        run_id=args.run_id,
        phase=args.phase,
        model=args.model,
        code_sha=args.code_sha,
        preregistration_sha256=sha256_bytes(args.preregistration.read_bytes()) if args.preregistration else None,
        agent_cmd=tuple(shlex.split(args.agent_cmd)),  # e.g. "setpriv --reuid=… -- claude" in the image
        memkernel_cmd=args.memkernel_cmd,
        memkernel_python=args.memkernel_python,
        tasks_root=args.tasks_root,
        oracles_root=args.oracles_root,
        timeout_s=args.timeout,
        shared_cache=args.shared_cache,
        wiki_studio_cmd=args.wiki_studio_cmd,
        hooks_dir=args.hooks_dir,
        ledger_script=args.ledger_script,
        agent_uid=args.agent_uid,
        agent_gid=args.agent_gid,
    )
    print(run(cfg, args.task, args.arm, args.runs))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

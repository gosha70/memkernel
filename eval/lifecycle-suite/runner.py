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
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

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

SUITE_DIR = Path(__file__).resolve().parent
REPO_ROOT = SUITE_DIR.parents[1]
ARMS_DIR = SUITE_DIR / "arms"
HOOK_SCRIPTS = {
    "SessionStart": "session-start.py",
    "PreCompact": "pre-compact.py",
    "PostCompact": "post-compact.py",
}
BASE_TOOLS = ("Read", "Grep", "Glob", "Bash", "Write", "Edit")
ARM_NAMES = ("bare", "placebo", "protocol", "claude_md", "fs_grep", "memkernel", "wiki_studio")
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

    def runs_on(self, task: Task) -> bool:
        return not self.groups or task.group in self.groups


def load_arm(name: str, arms_dir: Path = ARMS_DIR) -> Arm:
    config_path = arms_dir / name / "config.frozen.json"
    raw = config_path.read_bytes()
    config = json.loads(raw)
    instruction = (arms_dir / name / config["instruction"]).read_bytes() if config.get("instruction") else b""
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
        config_sha256=sha256_bytes(raw + b"\0" + instruction),
        groups=tuple(config.get("groups", [])),
        cli_pin=(config["cli_pin"]["command"], config["cli_pin"]["version"]) if config.get("cli_pin") else None,
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
        shared_artifact=spec.get("shared_artifact"),
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


def _instruction_file(arm: Arm, dirs: SessionDirs) -> Path | None:
    if not arm.instruction:
        return None
    text = arm.instruction.decode("utf-8")
    if dirs.memory_dir is not None:
        text = text.replace(MEMORY_DIR_TOKEN, str(dirs.memory_dir))
    path = dirs.root / "instruction.md"
    path.write_text(text, encoding="utf-8")
    return path


def _memkernel_env(dirs: SessionDirs, chain_id: str, cfg: RunConfig) -> dict[str, str]:
    assert dirs.store is not None
    env = {
        "MEMKERNEL_PROJECT_ID": f"lc_{sha256_text(chain_id + '/' + dirs.namespace)[:16]}",
        "MEMKERNEL_CHROMA_PERSIST_PATH": str(dirs.store),
        "MEMKERNEL_PROJECT_ROOT": str(dirs.workspace),
        "MEMKERNEL_WIKI_DIR": str(dirs.workspace / WIKI_DIR),
        "HOME": str(dirs.home),
    }
    if cfg.shared_cache is not None:
        env["HF_HOME"] = str(cfg.shared_cache / "huggingface")
        # The cache is the model's only source: never contact the Hub, so the embedding model cannot change
        # between calibration and the measured run (the image pins the cached revision).
        env["HF_HUB_OFFLINE"] = "1"
    return env


def _write_wiring(arm: Arm, dirs: SessionDirs, chain_id: str, cfg: RunConfig, ledger: Path) -> list[str]:
    args: list[str] = []
    if arm.mcp:
        mcp = {
            "mcpServers": {
                "memkernel": {"command": cfg.memkernel_cmd, "args": [], "env": _memkernel_env(dirs, chain_id, cfg)}
            }
        }
        mcp_path = dirs.root / "mcp.json"
        mcp_path.write_text(json.dumps(mcp, indent=2), encoding="utf-8")
        args += ["--mcp-config", str(mcp_path), "--strict-mcp-config"]
    if arm.hooks:
        hooks: dict[str, Any] = {}
        for event in arm.hooks:
            target = (
                list(cfg.hook_command_override)
                if cfg.hook_command_override
                else [cfg.memkernel_python, str(REPO_ROOT / "templates" / "hooks" / HOOK_SCRIPTS[event])]
            )
            command = [
                sys.executable,
                str(SUITE_DIR / "hook_ledger.py"),
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
    instruction = _instruction_file(arm, dirs)
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
        env.update(_memkernel_env(dirs, chain_id, cfg))  # hooks read the same MEMKERNEL_* as the server
    return env


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
        proc = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
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
    if observe is not None and invalid is None:
        observe(task, arm, position, dirs)
    ledger = dirs.root / "hook-ledger.jsonl"
    if invalid is None:
        wiring = _write_wiring(arm, dirs, chain_id, cfg, ledger)
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
            if summary.authentication_failed:  # the API refused the key: the agent could not act (FR-015a)
                invalid = "session_not_started"
                break
            if index == 0 and arm.mcp and summary.mcp_status.get("memkernel") not in CONNECTED_STATUSES:
                invalid = "mcp_not_connected"
                break
            if result.timed_out:
                timed_out = True
                break
        hooks = _read_ledger(ledger)
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
        "wall_time_ms": int((time.monotonic() - t0) * 1000),
        "stages": {"exposure_at": exposure_at, "evaluation_at": evaluation_at, "compactions": summary.compactions},
        "diagnostics": session_diagnostics(summary, dirs.workspace, earlier_reads, hooks),
        "hashes": {
            "prompt": sha256_text("\n".join(prompts)),
            "response": sha256_text(summary.response),
            "tool_payloads": tool_payload_digest(summary),
        },
    }
    if timed_out and receipt["valid"]:
        receipt["outcome"] = "timeout"  # a valid failure of this session; the chain inherits it (FR-015a)
    return SessionOutcome(receipt, summary, dirs, prompts, timed_out)


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
        passed, _detail = _load_checker(task).check(final.dirs.workspace, task.oracle_dir(cfg.oracles_root))
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
    chain_dir.mkdir(parents=True)
    state = ChainState()
    earlier_reads: set[str] = set()
    receipts: list[dict[str, Any]] = []
    outcome: SessionOutcome | None = None
    for position in range(len(task.sessions)):
        outcome = run_session(task, arm, run_index, position, chain_dir, state, earlier_reads, cfg, observe)
        receipts.append(outcome.receipt)
        if not outcome.receipt["valid"]:
            break
        earlier_reads |= set(read_paths(outcome.summary, outcome.dirs.workspace))
        transcript = chain_dir / f"transcript-{position}.md"
        transcript.write_text(render_transcript(outcome.prompts, outcome.summary), encoding="utf-8")
        state = ChainState(workspace=outcome.dirs.workspace, transcripts=[*state.transcripts, transcript])
    # Calibration is never graded: nobody sees pass/fail before the preregistration is committed, so its
    # receipts carry usage and stream evidence only. Measured and demo runs are graded exactly as before.
    gradeable = cfg.phase != CALIBRATION_PHASE
    if gradeable and outcome is not None and outcome.receipt["valid"] and outcome.receipt["stage"] == "evaluation":
        earlier_timeout = any(r["outcome"] == "timeout" for r in receipts[:-1])
        grade(task, arm, outcome, cfg, earlier_timeout=earlier_timeout)
    for receipt in receipts:
        errors = validate_receipt(receipt)
        if errors:
            raise ValueError(f"receipt does not match the schema: {errors}")
    return receipts


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


def check_cli_pin(arm: Arm) -> None:
    """Refuse a paid run unless ``arm``'s pinned command reports its pinned version on the session PATH."""
    if arm.cli_pin is None:
        return
    command, version = arm.cli_pin
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


def run(cfg: RunConfig, task_ids: list[str], arm_names: list[str], runs: int, observe: Any = None) -> Path:
    """Run every chain of ``task_ids`` × ``arm_names`` × ``runs`` and write the receipts under the run root.

    The CLI refuses a calibration or measured phase without ``--shared-cache``; callers outside the CLI must pass
    a shared cache for those phases themselves, or the memkernel server goes online for its embedding model.
    """
    if _inside_checkout(cfg.run_root):
        raise SystemExit(f"refusing to run inside a git checkout: {cfg.run_root}")
    out = cfg.run_root / cfg.run_id
    if out.exists() and any(out.iterdir()):
        raise SystemExit(f"run directory is not empty: {out}")
    out.mkdir(parents=True, exist_ok=True)
    receipts_path = out / "receipts.jsonl"
    tasks = [load_task(cfg.tasks_root / task_id) for task_id in task_ids]
    arms = [load_arm(name) for name in arm_names]
    if cfg.phase in (CALIBRATION_PHASE, MEASURED_PHASE):
        for arm in arms:
            check_cli_pin(arm)
    with receipts_path.open("w", encoding="utf-8") as sink:
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

DEMO_TASKS = ("demo-retain", "demo-wiki", "demo-compact")


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
        }

    with tempfile.TemporaryDirectory() as tmp:
        cfg = RunConfig(
            run_root=Path(tmp),
            run_id="demo",
            phase="demo",
            model="stub",
            code_sha="demo",
            preregistration_sha256=None,
            agent_cmd=(sys.executable, str(SUITE_DIR / "stub_agent.py")),
            memkernel_cmd="stub-memkernel",
            memkernel_python=sys.executable,
            tasks_root=SUITE_DIR / "fixtures" / "demo-tasks",
            oracles_root=SUITE_DIR / "fixtures" / "demo-oracles",
            timeout_s=60.0,
            hook_command_override=(sys.executable, "-c", "import sys; sys.stdin.read()"),
        )
        receipts_path = run(cfg, list(DEMO_TASKS), list(ARM_NAMES), runs=1, observe=observe)
        receipts = [json.loads(line) for line in receipts_path.read_text(encoding="utf-8").splitlines()]

    failures = check_demo(seen, receipts)
    for line in failures:
        print(f"FAIL {line}")
    print(f"demo: {len(receipts)} receipts, {len(seen)} sessions observed, {len(failures)} failure(s)")
    return 1 if failures else 0


def check_demo(seen: dict[tuple[str, str, int], dict[str, bool]], receipts: list[dict[str, Any]]) -> list[str]:
    failures: list[str] = []
    rules = {arm: load_arm(arm) for arm in ARM_NAMES}
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
    return failures


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
        agent_cmd=(args.agent_cmd,),
        memkernel_cmd=args.memkernel_cmd,
        memkernel_python=args.memkernel_python,
        tasks_root=args.tasks_root,
        oracles_root=args.oracles_root,
        timeout_s=args.timeout,
        shared_cache=args.shared_cache,
    )
    print(run(cfg, args.task, args.arm, args.runs))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

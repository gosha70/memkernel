# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""Count-based diagnostics over a chain's session streams (FR-018). Never endpoints."""

from __future__ import annotations

import json
import re
import shlex
from pathlib import Path
from typing import TYPE_CHECKING, Any

from records import MEMKERNEL_TOOL_PREFIX

if TYPE_CHECKING:
    from records import StreamSummary

READ_TOOL = "Read"
BASH_TOOL = "Bash"
WRITE_TOOLS = ("Write", "Edit")
WIKI_DIR = "knowledge/wiki"  # the lc-wiki shared artifact, at this path in every workspace
WIKI_STUDIO = "wiki-studio"
NESTED_MODEL_VERBS = ("ingest", "query")  # wiki-studio verbs that start a model the receipts cannot see
_VALUE_FLAGS = ("--root", "--wiki-dir", "--proposals-dir", "--backend", "--output-dir")
_SEPARATORS = {";", "&&", "||", "|", "&", "(", ")", "{", "}", "!"}
_WRAPPERS = {"env", "command", "exec", "nohup", "time", "sudo", "uvx", "nice"}  # run the next word as a command
_SHELLS = {"sh", "bash", "zsh", "dash"}
_HEREDOC = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")
_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_SINGLE_QUOTED = re.compile(r"'[^']*'")
_SUBSTITUTION = re.compile(r"\$\(([^()]*)\)|`([^`]*)`")  # $(...) and `...` run their contents, even inside an argument


def _ratio(numerator: int, denominator: int) -> dict[str, int]:
    return {"numerator": numerator, "denominator": denominator}


def _relative(path: str, workspace: Path) -> str:
    candidate = Path(path)
    try:
        return candidate.resolve().relative_to(workspace.resolve()).as_posix()
    except (ValueError, OSError):
        return candidate.as_posix()


def read_paths(summary: StreamSummary, workspace: Path) -> list[str]:
    return [
        _relative(str(use.input.get("file_path", "")), workspace)
        for use in summary.tool_uses
        if use.name == READ_TOOL and use.input.get("file_path")
    ]


def _command_lines(command: str) -> list[str]:
    """The lines of a shell script that are commands: heredoc bodies are data, not commands."""
    lines, delimiter = [], None
    for line in command.splitlines():
        if delimiter is not None:
            if line.strip() == delimiter:
                delimiter = None
            continue
        lines.append(line)
        match = _HEREDOC.search(line)
        if match:
            delimiter = match.group(2)
    return lines


def _simple_commands(line: str) -> list[list[str]]:
    lexer = shlex.shlex(line, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    try:
        tokens = list(lexer)
    except ValueError:
        tokens = line.split()
    commands, current = [], []
    for token in tokens:
        if token in _SEPARATORS:
            if current:
                commands.append(current)
            current = []
        else:
            current.append(token)
    if current:
        commands.append(current)
    return commands


def _wiki_studio_verbs(command: str, depth: int = 0) -> list[str]:
    """The wiki-studio verbs a Bash command line executes; words passed as arguments (echo, grep) never count."""
    verbs: list[str] = []
    for line in _command_lines(command):
        if depth < 3:
            for match in _SUBSTITUTION.finditer(_SINGLE_QUOTED.sub("''", line)):  # '...' is literal text
                verbs += _wiki_studio_verbs(match.group(1) or match.group(2) or "", depth + 1)
        for words in _simple_commands(line):
            index = 0
            while index < len(words) and (_ASSIGNMENT.match(words[index]) or words[index] in _WRAPPERS):
                index += 1
                while index < len(words) and words[index].startswith("-") and words[index - 1] == "env":
                    index += 1  # env's own flags
            if index >= len(words):
                continue
            program, args = Path(words[index]).name, words[index + 1 :]
            if program in _SHELLS and "-c" in args and depth < 3:
                script_at = args.index("-c") + 1
                if script_at < len(args):
                    verbs += _wiki_studio_verbs(args[script_at], depth + 1)
                continue
            module_run = program.startswith("python") and args[:2] == ["-m", "wiki_studio"]
            if module_run or (program == "pipx" and args[:2] == ["run", WIKI_STUDIO]):
                args = args[2:]
            elif program != WIKI_STUDIO:
                continue
            rest = iter(args)
            for arg in rest:
                if arg.startswith("--"):
                    if arg in _VALUE_FLAGS:
                        next(rest, None)
                    continue
                verbs.append(arg)
                break
    return verbs


def _ref_ids(text: str) -> list[str]:
    try:
        parsed: Any = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return []
    items = parsed if isinstance(parsed, list) else [parsed]
    return [str(item["ref_id"]) for item in items if isinstance(item, dict) and item.get("ref_id")]


def session_diagnostics(
    summary: StreamSummary, workspace: Path, earlier_reads: set[str], hooks: list[dict[str, Any]]
) -> dict[str, dict[str, int]]:
    """Numerator/denominator pairs for one session given the paths earlier sessions of its chain read."""
    reads = read_paths(summary, workspace)
    re_reads = sum(1 for path in reads if path in earlier_reads)

    total_calls = len(summary.tool_uses)
    first_retain = next(
        (i for i, use in enumerate(summary.tool_uses) if use.name == f"{MEMKERNEL_TOOL_PREFIX}retain"), total_calls
    )

    returned: list[str] = []
    used: set[str] = set()
    for use in summary.tool_uses:
        if use.name == f"{MEMKERNEL_TOOL_PREFIX}recall":
            returned += _ref_ids(summary.tool_results.get(use.tool_id, ""))
        elif use.name in (f"{MEMKERNEL_TOOL_PREFIX}get", f"{MEMKERNEL_TOOL_PREFIX}ask") and use.input.get("ref_id"):
            used.add(str(use.input["ref_id"]))
    unique_returned = list(dict.fromkeys(returned))

    bash = [use for use in summary.tool_uses if use.name == BASH_TOOL]
    nested = sum(
        1 for use in bash if set(_wiki_studio_verbs(str(use.input.get("command", "")))) & set(NESTED_MODEL_VERBS)
    )
    writes = [use for use in summary.tool_uses if use.name in WRITE_TOOLS]
    wiki_writes = sum(
        1
        for use in writes
        if (_relative(str(use.input.get("file_path", "")), workspace) + "/").startswith(WIKI_DIR + "/")
    )

    return {
        "re_reads_after_resume": _ratio(re_reads, len(reads)),
        "calls_before_first_retain": _ratio(first_retain, total_calls),
        "recall_to_use": _ratio(sum(1 for ref in unique_returned if ref in used), len(unique_returned)),
        "hooks_succeeded": _ratio(sum(1 for h in hooks if h["exit_status"] == 0), len(hooks)),
        # read for wiki_studio: a nested model whose tokens are not in the receipt, and pages that bypassed the gate
        "wiki_studio_nested_model_calls": _ratio(nested, len(bash)),
        "direct_wiki_writes": _ratio(wiki_writes, len(writes)),
    }

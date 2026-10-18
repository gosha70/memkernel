# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""Count-based diagnostics over a chain's session streams (FR-018). Never endpoints."""

from __future__ import annotations

import json
import re
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
_WRAPPERS = {"env", "command", "exec", "nohup", "time", "sudo", "uvx", "nice"}  # run the next word as a command
_KEYWORDS = {"!", "{", "}", "if", "then", "else", "elif", "do", "while", "until"}  # precede a command
_SHELLS = {"sh", "bash", "zsh", "dash"}
_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_OPERATORS = ("&&", "||", ";;", ";", "&", "|", "(", ")")
_REDIRECT = "<redirect>"
_MAX_DEPTH = 4


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


def _closing(script: str, start: int) -> int:
    """Index just past the ``)`` that closes the ``$(`` opened before ``start``; quotes and nesting respected."""
    depth, i = 1, start
    while i < len(script):
        char = script[i]
        if char == "\\":
            i += 2
            continue
        if char == "'":
            i = script.find("'", i + 1) + 1 or len(script)
            continue
        if char == '"':
            i += 1
            while i < len(script) and script[i] != '"':
                i += 2 if script[i] == "\\" else 1
            i += 1
            continue
        depth += char == "("
        depth -= char == ")"
        i += 1
        if depth == 0:
            return i
    return len(script)


def _heredoc_substitutions(body: str) -> list[str]:
    """Substitutions an unquoted heredoc body runs: quotes are plain text there; only \\$, \\` and \\\\ escape."""
    found: list[str] = []
    i = 0
    while i < len(body):
        if body[i] == "\\" and i + 1 < len(body) and body[i + 1] in "$`\\":
            i += 2
        elif body.startswith("$(", i):
            close = _closing(body, i + 2)
            found.append(body[i + 2 : close - 1])
            i = close
        elif body[i] == "`":
            close = body.find("`", i + 1)
            close = len(body) if close < 0 else close
            found.append(body[i + 1 : close])
            i = close + 1
        else:
            i += 1
    return found


def _lex(script: str) -> tuple[list[list[str]], list[str], dict[int, str]]:
    """Split a Bash script into simple commands (unquoted words) and the substitutions it would run.

    Follows the shell where it matters for "which program runs": backslash-newline
    joins lines, quotes make operators and ``#`` literal, comments are skipped,
    ``$(...)`` and backticks run outside single quotes, heredoc bodies are data
    except for substitutions in an unquoted heredoc, and redirection targets are
    not arguments.
    """
    commands: list[list[str]] = []
    substitutions: list[str] = []
    bodies: dict[int, str] = {}  # command index -> its heredoc body (``sh <<EOF`` runs it)
    words: list[str] = []
    word: list[str] = []
    in_word = False
    heredocs: list[tuple[str, bool, int]] = []  # (delimiter, body expands substitutions, command index)
    i, n = 0, len(script)

    def end_word() -> None:
        nonlocal word, in_word
        if in_word:
            words.append("".join(word))
        word, in_word = [], False

    def end_command() -> None:
        nonlocal words
        end_word()
        if words:
            commands.append(words)
        words = []

    def substitution_at(index: int) -> int:
        if script.startswith("$(", index):
            close = _closing(script, index + 2)
            substitutions.append(script[index + 2 : close - 1])
            return close
        close = script.find("`", index + 1)
        close = n if close < 0 else close
        substitutions.append(script[index + 1 : close])
        return close + 1

    while i < n:
        char = script[i]
        if char == "\\" and i + 1 < n:
            if script[i + 1] != "\n":  # backslash-newline is a continuation and vanishes
                word.append(script[i + 1])
                in_word = True
            i += 2
        elif char == "'":
            close = script.find("'", i + 1)
            close = n if close < 0 else close
            word.append(script[i + 1 : close])
            in_word, i = True, close + 1
        elif char == '"':
            i += 1
            while i < n and script[i] != '"':
                if script[i] == "\\" and i + 1 < n:
                    word.append(script[i + 1])
                    i += 2
                elif script.startswith("$(", i) or script[i] == "`":
                    start = i
                    i = substitution_at(i)
                    word.append(script[start:i])
                else:
                    word.append(script[i])
                    i += 1
            in_word, i = True, i + 1
        elif script.startswith("$(", i) or char == "`":
            start = i
            i = substitution_at(i)
            word.append(script[start:i])
            in_word = True
        elif char == "#" and not in_word:
            newline = script.find("\n", i)
            i = n if newline < 0 else newline
        elif char == "\n":
            end_command()
            i += 1
            for delimiter, expands, owner in heredocs:
                body: list[str] = []
                while i < n:
                    newline = script.find("\n", i)
                    line_end = n if newline < 0 else newline
                    line = script[i:line_end]
                    i = line_end + 1
                    if line.strip() == delimiter:
                        break
                    body.append(line)
                bodies[owner] = "\n".join(body)
                if expands:
                    substitutions.extend(_heredoc_substitutions(bodies[owner]))
            heredocs = []
        elif char in " \t":
            end_word()
            i += 1
        elif script.startswith("<<<", i):  # here-string: its word is expanded like any word, no body follows
            end_word()
            i += 3
            words.append(_REDIRECT)
        elif script.startswith("<<", i):
            end_word()
            i += 3 if script.startswith("<<-", i) else 2
            while i < n and script[i] in " \t":
                i += 1
            quoted = i < n and script[i] in "'\""
            delimiter = []
            while i < n and script[i] not in " \t\n;&|<>()":
                if script[i] not in "'\"\\":
                    delimiter.append(script[i])
                i += 1
            heredocs.append(("".join(delimiter), not quoted, len(commands)))
        elif char in "<>":
            if in_word and "".join(word).isdigit():  # 2>file: the digit names a stream, not a word
                word, in_word = [], False
            end_word()
            while i < n and script[i] in "<>&":
                i += 1
            words.append(_REDIRECT)
        else:
            operator = next((op for op in _OPERATORS if script.startswith(op, i)), None)
            if operator:
                end_command()
                i += len(operator)
            else:
                word.append(char)
                in_word = True
                i += 1
    end_command()
    for command in commands:  # a redirection takes the next word as its target
        while _REDIRECT in command:
            at = command.index(_REDIRECT)
            del command[at : at + 2]
    return commands, substitutions, bodies


def _wiki_studio_verbs(command: str, depth: int = 0) -> list[str]:
    """The wiki-studio verbs a Bash command would execute; words that are only printed or quoted never count.

    Static: every command in a command position counts, including one behind a
    condition (``a || wiki-studio query``), so a possible nested model is
    flagged rather than missed. Scripts handed to ``sh -c``, ``eval`` or a shell
    reading a heredoc are read too. Not detected: a program name that only a
    variable holds (``$w query``) and a script piped into a shell
    (``printf ... | sh``); both need the command to run to be known.
    """
    if depth > _MAX_DEPTH:
        return []
    commands, substitutions, bodies = _lex(command)
    verbs: list[str] = []
    for script in substitutions:
        verbs += _wiki_studio_verbs(script, depth + 1)
    for position, words in enumerate(commands):
        index = 0
        while index < len(words) and (
            _ASSIGNMENT.match(words[index]) or words[index] in _WRAPPERS or words[index] in _KEYWORDS
        ):
            index += 1
            while index < len(words) and words[index].startswith("-") and words[index - 1] == "env":
                index += 1  # env's own flags
        if index >= len(words):
            continue
        program, args = Path(words[index]).name, words[index + 1 :]
        if program in _SHELLS and "-c" in args:
            script_at = args.index("-c") + 1
            if script_at < len(args):
                verbs += _wiki_studio_verbs(args[script_at], depth + 1)
            continue
        if program in _SHELLS and position in bodies:  # sh <<EOF: the heredoc is the script
            verbs += _wiki_studio_verbs(bodies[position], depth + 1)
            continue
        if program == "eval":
            verbs += _wiki_studio_verbs(" ".join(args), depth + 1)
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

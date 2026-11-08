# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""Curation debt at session start (memkernel-0-7-governed G2).

What in the wiki needs a curator, from wiki-studio's ``findings`` and memkernel's sync ledger, in a few lines.
Everything that touches wiki-studio or a ledger file runs in one spawned child process, so the session-start
block is never held up past :data:`CURATION_DEBT_TIMEOUT_SECONDS` plus the two reaping graces once the child has
started, whatever the child does. Only an in-memory store's ledger is counted in this process, without waiting for
its lock.
"""

from __future__ import annotations

import contextlib
import importlib
import multiprocessing
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from memkernel.wiki.ledger import (
    LedgerUnavailableError,
    snapshot_unfinished,
    snapshot_unfinished_in_memory,
    wiki_key,
)
from memkernel.wiki.studio import (
    WIKI_MODE_GOVERNED,
    WIKI_MODE_UNGATED,
    GateError,
    curation_findings,
    gate_available,
    governed_preflight,
    wiki_id,
)

if TYPE_CHECKING:
    from multiprocessing.connection import Connection

    from memkernel.config import MemKernelSettings

HEADING_CURATION_DEBT = "### Curation debt"
CURATION_DEBT_BUDGET = 500  # characters of the rendered section, lent from the context share
CURATION_DEBT_MAX_LINES = 3  # example lines
CURATION_DEBT_FIELD_CHARS = 200  # each string the child sends is cut to this
CURATION_DEBT_TIMEOUT_SECONDS = 2.0
CURATION_DEBT_TERM_GRACE_SECONDS = 0.3
CURATION_DEBT_KILL_GRACE_SECONDS = 0.2
CURATION_DEBT_DEADLINE_CHECK_EVERY = 100  # in-memory ledger entries between two deadline checks
CURATION_REVIEW_KINDS = ("unapproved", "approval-stale", "approval-policy-changed", "superseded-still-indexed")
# memkernel's own order, never wiki-studio's dictionary order; a kind not listed follows, by name.
CURATION_KIND_ORDER = (
    *CURATION_REVIEW_KINDS,
    "open-conflict",
    "conflict-one-sided",
    "conflict-dangling",
    "stale-claim",
    "weak-orphan",
    "missing-cross-link",
    "avoid-format",
    "no-page-id",
)
SYNC_PENDING_LABEL, SYNC_FAILED_LABEL = "sync pending", "sync failed"
CURATION_HINT = "Run `wiki-studio findings` for the full list."
UNAVAILABLE_PREFIX = "Curation debt unavailable: "
TIMED_OUT, NOT_REAPED, NO_RESULT = "timed out", "not reaped", "the check ended without a result"
HOOK_START, HOOK_FINDINGS, HOOK_SEND = "start", "findings", "send"

# Tests only: "module:function" the child imports and calls with each HOOK_* stage (it never sees this process's
# patches).
TEST_HOOK: str | None = None
_CONTEXT = multiprocessing.get_context("spawn")
_RESULT_ABSENT, _RESULT_ERROR = "absent", "error"


def curation_debt_lines(settings: MemKernelSettings, store_settings: MemKernelSettings, project_id: str) -> list[str]:
    """The ``### Curation debt`` section (with its leading blank line), or nothing: no wiki, ``ungated``, wiki-studio
    absent, or no debt. Any failure is one ``Curation debt unavailable`` line; this never raises."""
    if not settings.wiki_dir or settings.wiki_mode == WIKI_MODE_UNGATED:
        return []
    try:
        persisted = bool(store_settings.chroma_persist_path.strip())
        args = (
            settings.wiki_dir,
            settings.project_root,
            settings.wiki_mode == WIKI_MODE_GOVERNED,
            store_settings.state_dir if persisted else None,
            project_id,
            TEST_HOOK,
        )
        result, deadline = _run_child(args)
        if _RESULT_ERROR in result:
            return _unavailable(str(result[_RESULT_ERROR]))
        if _RESULT_ABSENT in result:
            return []
        if not persisted:
            result["pending"], result["failed"] = snapshot_unfinished_in_memory(
                project_id, str(result["key"]), deadline, CURATION_DEBT_DEADLINE_CHECK_EVERY
            )
        return _render(result)
    except LedgerUnavailableError as exc:
        return _unavailable(str(exc))
    except Exception as exc:  # the pipe or the cleanup failed: never the hook's failure (G2)
        return _unavailable(f"the check failed: {exc}")


def _run_child(args: tuple[Any, ...]) -> tuple[dict[str, Any], float]:
    """Start the child, wait for its one result, and reap it within the two graces; also return the deadline.

    ``Process.start()`` runs on this thread and cannot be interrupted, so the deadline is taken once it returns: the
    bound covers the check, not a fork or exec the operating system holds up (G2, as the owner decided on
    2026-11-04).
    """
    receiver, sender = _CONTEXT.Pipe(duplex=False)
    process = None
    deadline = time.monotonic() + CURATION_DEBT_TIMEOUT_SECONDS
    result: dict[str, Any] = {_RESULT_ERROR: NO_RESULT}
    try:
        try:
            process = _CONTEXT.Process(target=_child, args=(sender, *args), daemon=True)
            process.start()
        except Exception as exc:  # any failure to start is the unavailable line, never the hook's failure
            result = {_RESULT_ERROR: f"could not start the check: {exc}"}
        else:
            deadline = time.monotonic() + CURATION_DEBT_TIMEOUT_SECONDS
            _close(sender)  # the parent's copy of the write end, right after the start
            try:
                if receiver.poll(max(0.0, deadline - time.monotonic())):
                    received = receiver.recv()
                    result = received if isinstance(received, dict) else {_RESULT_ERROR: NO_RESULT}
                else:
                    result = {_RESULT_ERROR: TIMED_OUT}
            except Exception:  # EOF, a broken pipe or an unreadable message: never the hook's failure
                result = {_RESULT_ERROR: NO_RESULT}
            process.join(max(0.0, deadline - time.monotonic()))
    finally:
        try:  # each step runs whatever the one before it did
            _close(sender, receiver)
        finally:
            if process is not None and not _reap(process):
                result = {_RESULT_ERROR: NOT_REAPED}
    return result, deadline


def _close(*connections: Connection) -> None:
    for connection in connections:
        with contextlib.suppress(Exception):
            connection.close()


def _reap(process: multiprocessing.process.BaseProcess) -> bool:
    """terminate, then kill, each with its own bounded join; close a reaped child. False if it outlived both."""
    if process.is_alive():
        process.terminate()
        process.join(CURATION_DEBT_TERM_GRACE_SECONDS)
    if process.is_alive():
        process.kill()
        process.join(CURATION_DEBT_KILL_GRACE_SECONDS)
    if process.is_alive():
        return False  # left to the operating system; Process.close() refuses a live process
    process.close()
    return True


def _child(
    sender: Connection,
    wiki_dir: str,
    project_root: str,
    governed: bool,
    state_dir: str | None,
    project_id: str,
    hook: str | None,
) -> None:
    """The child: one bounded dict through ``sender``, which is closed whatever happens."""
    try:
        call = _load_hook(hook)
        call(HOOK_START)
        result = _collect(Path(wiki_dir), Path(project_root), governed, state_dir, project_id, call)
        call(HOOK_SEND)
        sender.send(result)
    finally:
        sender.close()


def _load_hook(hook: str | None) -> Any:
    if hook is None:
        return lambda stage: None
    module, _, name = hook.partition(":")
    return getattr(importlib.import_module(module), name)


def _collect(
    wiki_dir: Path, project_root: Path, governed: bool, state_dir: str | None, project_id: str, call: Any
) -> dict[str, Any]:
    if not wiki_dir.is_dir():
        return {_RESULT_ABSENT: True}
    try:
        if governed:
            api = governed_preflight(wiki_dir, project_root)  # a wiki that fails it is never read
        else:
            api = gate_available()
            if api is None:
                return {_RESULT_ABSENT: True}
        key = wiki_key(wiki_id(api, wiki_dir, project_root), wiki_dir, project_root)
        call(HOOK_FINDINGS)
        counts, findings = curation_findings(api, wiki_dir, project_root)
        pending, failed = snapshot_unfinished(state_dir, project_id, key) if state_dir is not None else (0, 0)
    except (GateError, LedgerUnavailableError, OSError) as exc:
        return {_RESULT_ERROR: _cut(str(exc))}
    review = set(CURATION_REVIEW_KINDS)
    examples = sorted(findings, key=lambda f: (f[0] not in review, *_rank(f[0])))[:CURATION_DEBT_MAX_LINES]
    return {
        "counts": {_cut(kind): count for kind, count in counts.items()},
        "examples": [(_cut(kind), _cut(page)) for kind, page in examples],
        "pending": pending,
        "failed": failed,
        "key": key,
    }


def _rank(kind: str) -> tuple[int, str]:
    order = {name: index for index, name in enumerate(CURATION_KIND_ORDER)}
    return order.get(kind, len(order)), kind


def _cut(text: str) -> str:
    return text[:CURATION_DEBT_FIELD_CHARS]


def _render(result: dict[str, Any]) -> list[str]:
    """The section within CURATION_DEBT_BUDGET: the counts line, then as many examples as fit, then the hint."""
    counts: dict[str, int] = result["counts"]
    parts = [f"{kind} {counts[kind]}" for kind in sorted(counts, key=_rank)]
    parts += [
        f"{label} {result[key]}" for label, key in ((SYNC_PENDING_LABEL, "pending"), (SYNC_FAILED_LABEL, "failed"))
    ]
    parts = [part for part in parts if not part.endswith(" 0")]
    if not parts:
        return []
    head = ["", HEADING_CURATION_DEBT]
    room = CURATION_DEBT_BUDGET - len("\n".join([*head, "", CURATION_HINT]))
    lines = [*head, _clip(", ".join(parts), room)]
    from memkernel.lifecycle import STORED_KIND_DEBT, stored  # lazily: lifecycle imports this module

    for kind, page in result["examples"]:
        line = f"- {kind}: {stored(page, STORED_KIND_DEBT)}"  # the page path comes from the wiki: quoted as data
        if len("\n".join([*lines, line, CURATION_HINT])) > CURATION_DEBT_BUDGET:
            break
        lines.append(line)
    return [*lines, CURATION_HINT]


def _unavailable(reason: str) -> list[str]:
    room = CURATION_DEBT_BUDGET - len(f"\n{HEADING_CURATION_DEBT}\n{UNAVAILABLE_PREFIX}")
    return ["", HEADING_CURATION_DEBT, f"{UNAVAILABLE_PREFIX}{_clip(' '.join(reason.split()), room)}"]


def _clip(text: str, room: int) -> str:
    return text if len(text) <= room else f"{text[: max(0, room - 1)]}…"

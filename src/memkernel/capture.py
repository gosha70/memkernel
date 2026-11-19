# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""Capture (memkernel-0-12-capture-core, memkernel-0-14-capture-signals): signals from ended sessions' transcripts.

Three extractors: failed-then-fixed commands (S2), the owner's answers to ``AskUserQuestion`` and one session-outcome
record per session (S3), each with its own per-session cap.

At normal startup, with ``MEMKERNEL_CAPTURE`` on, each ended session still in the spool is read through a
``TranscriptReaderPort``. A ``Bash`` command that failed with its own exit status and later passed when run again
(D7) becomes one short-term ``observation``, redacted (FR-006), keyed by (session, the failing call's
``tool_use_id``, extractor) with the extractor version as a tag (D1, R2). A session leaves the spool only after its
records are stored (FR-002). One capture runs at a time (R3), within a time budget and record caps (D6).

The failure, rerun and stored-error rules here are also the repeated-mistake count's (``eval/repeat-mistakes``,
FR-011): one definition for both.
"""

from __future__ import annotations

import logging
import re
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from memkernel import session_spool
from memkernel.core.models import (
    CAPTURE_ANSWER_CANDIDATES,
    CAPTURE_CALL_TAG,
    CAPTURE_EXTRACTOR_OWNER_ANSWER,
    CAPTURE_EXTRACTOR_TAG,
    CAPTURE_ORIGIN_TAG,
    CAPTURE_SESSION_TAG,
    CAPTURE_SOURCE,
    CAPTURE_VERSION_TAG,
    MemoryType,
    TranscriptTooLargeError,
)

try:
    import fcntl
except ImportError:  # not POSIX: no lock, so no capture (R6)
    fcntl = None  # type: ignore[assignment]

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from memkernel.config import MemKernelSettings
    from memkernel.core.models import ToolStep, TranscriptSession
    from memkernel.core.ports import TranscriptReaderPort
    from memkernel.core.services import MemoryService
    from memkernel.session_spool import DrainResult, SessionWindow

logger = logging.getLogger(__name__)

EXTRACTOR = "failed-then-fixed"
OWNER_ANSWER = CAPTURE_EXTRACTOR_OWNER_ANSWER  # memkernel-0-14-capture-signals FR-002
SESSION_OUTCOME = "session-outcome"  # FR-003
EXTRACTORS = (EXTRACTOR, OWNER_ANSWER, SESSION_OUTCOME)
EXTRACTOR_VERSION = 1
# D6 (the owner's, 2026-11-16).
CAPTURE_TIME_BUDGET = 3.0  # seconds of capture per startup; a soft stop between sessions
CAPTURE_MAX_RECORDS = 20  # records stored per run
CAPTURE_SESSION_MAX_RECORDS = 5  # signals kept per session; the rest are dropped and counted (R4)
CAPTURE_MISS_LIMIT = 3  # startups a missing or unreadable transcript is retried
CAPTURE_TRANSCRIPT_MAX_BYTES = 50 * 1024 * 1024  # a larger transcript is never read
CAPTURE_TEXT_MAX = 300  # characters of one command, error line or fix step
CAPTURE_FIX_STEPS = 5  # fix steps named per record
CAPTURE_LOCK_FILE = "capture.lock"  # beside the spool file: one capture at a time per project (R3)
# memkernel-0-14-capture-signals (the owner's D5, D6).
ANSWER_SESSION_MAX = 30  # owner answers kept per session: the last 30 in transcript order
ANSWER_TEXT_MAX = 600  # characters of the owner's own words in one answer (an option's text is far shorter)
OUTCOME_FILES = 10  # edited files named in a session outcome; the rest is a count
ANSWER_CANDIDATES = CAPTURE_ANSWER_CANDIDATES  # owner answers among the promotion candidates (applied in core)
OUTCOME_KEY = "session"  # a session outcome's call key: one record per session
ASK_TOOL = "AskUserQuestion"
OUTCOME_EDIT_TOOLS = frozenset({"Edit", "Write", "MultiEdit", "NotebookEdit"})
MCP_PREFIX = "mcp__"

# The count's stored-error words (memkernel-0-10-recall-log D5), shared with it (FR-005, FR-011).
ERROR_WORDS = ("Error", "Exception", "Traceback", "FAILED", "fatal")
BASH_TOOL = "Bash"
EDIT_TOOLS = frozenset({"Edit", "Write"})
EXIT_PREFIX = "Exit code "  # how Claude Code starts the result of a command that exited non-zero
REDACTED = "[REDACTED]"
NO_FIX_STEPS = "no other step"

# D7: a trailing output filter is a final pipeline segment with no other |, ;, &, < or >.
_TRAILING_FILTER = re.compile(r"\s*\|\s*(?:tail|head|grep)\b[^|;&<>]*$")
_TRAILING_STDERR = re.compile(r"\s*2>&1$")
_PIPEFAIL = re.compile(r"\bset\s+-[A-Za-z]*o\s+pipefail\b")
_BACKTICK_SPAN = re.compile(r"`([^`\n]+)`")
# FR-003: a GitHub PR or issue URL, and the gh commands that create or merge.
_GITHUB_URL = re.compile(r"https://github\.com/([\w.-]+)/([\w.-]+)/(pull|issues)/(\d+)")
_GH_CREATE = re.compile(r"\bgh\s+(?:pr|issue)\s+create\b")
_GH_MERGE = re.compile(r"\bgh\s+pr\s+merge\b")
_GH_MERGE_TARGET = re.compile(r"\bgh\s+pr\s+merge\s+#?(\d+)\b")
_GH_REPO_FLAG = re.compile(r"(?:-R|--repo)[=\s]+([\w.-]+/[\w.-]+)")
_REPO_REF = re.compile(r"\b([\w.-]+/[\w.-]+)#(\d+)\b")

# FR-006, best-effort: each match is replaced with REDACTED (for an assignment or header, only its value).
_PRIVATE_KEY = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(?:-----END [A-Z ]*PRIVATE KEY-----|\Z)", re.DOTALL)
_URL_CREDENTIALS = re.compile(r"\b([A-Za-z][A-Za-z0-9+.-]*://)[^/\s:@]+:[^/\s@]+@")
_AUTHORIZATION = re.compile(r"(?i)\b(authorization:\s*)[^\n\"']+")
_ASSIGNMENT = re.compile(
    r"(?i)\b([A-Za-z0-9_]*(?:key|token|secret|password)[A-Za-z0-9_]*\s*=\s*)(\"[^\"\n]*\"|'[^'\n]*'|[^\s\"']+)"
)
_TOKEN = re.compile(
    r"\b(?:AKIA[0-9A-Z]{12,}|ghp_[A-Za-z0-9]{20,}|gho_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}"
    r"|sk-[A-Za-z0-9_-]{16,}|xox[a-z]-[A-Za-z0-9-]{10,})"
)
# R16: a path-shaped token of these characters is judged piece by piece, split on "/", so a path keeps its
# components; any other token is judged whole. Path-shaped: it starts with "/" (also after "~", "." or "..") or a
# file extension follows it.
_TOKEN_CHARS = re.compile(r"(?<![A-Za-z0-9+/=_-])[A-Za-z0-9+/=_-]{16,}(?![A-Za-z0-9+/=_-])")
_EXTENSION = re.compile(r"\.[A-Za-z]")
_HEX = re.compile(r"[0-9a-fA-F]+")
LONG_PIECE = 32  # a piece this long that mixes letters and digits and is not all hexadecimal
MIXED_PIECE = 16  # a piece this long that mixes uppercase, lowercase and digits


@dataclass(frozen=True)
class Signal:
    """One captured record to store: its key within the session (``call``), content, extractor and type."""

    call: str
    content: str
    extractor: str = EXTRACTOR
    memory_type: MemoryType = MemoryType.OBSERVATION


@dataclass
class CaptureReport:
    """What one startup's capture did (FR-009); ``skipped`` when another startup held the capture lock."""

    stored: int = 0
    sessions: int = 0
    left: int = 0
    given_up: int = 0
    dropped: int = 0
    skipped: bool = False
    by_extractor: dict[str, int] = field(default_factory=dict)  # records stored per extractor (S3 FR-006)

    def line(self) -> str | None:
        """The startup report's line, or None when capture neither stored nor dropped anything."""
        if self.skipped or not (self.stored or self.sessions or self.left or self.given_up or self.dropped):
            return None
        counts = ", ".join(f"{name} {self.by_extractor[name]}" for name in EXTRACTORS if self.by_extractor.get(name))
        return (
            f"Capture: {self.stored} record(s) stored{f' ({counts})' if counts else ''} from {self.sessions} "
            f"session(s); {self.left} session(s) left "
            f"for the next start; {self.given_up} transcript(s) given up on; {self.dropped} signal(s) over the "
            "per-session cap dropped."
        )


# ── text rules ─────────────────────────────────────────────────────────────


def collapse(text: str) -> str:
    return " ".join(text.split())


def signatures(content: str) -> list[str]:
    """The stored errors in a memory's content, in order, without duplicates (FR-011, R9): backticked spans with an
    error word and more than one word, a word being a whitespace-separated token after :func:`collapse`."""
    spans = [collapse(s) for s in _BACKTICK_SPAN.findall(content)]
    return list(dict.fromkeys(s for s in spans if any(w in s for w in ERROR_WORDS) and len(s.split()) > 1))


def rerun_key(command: str) -> str:
    """The command a rerun must match (D7): whitespace collapsed, trailing ``| tail``, ``| head``, ``| grep`` and
    ``2>&1`` removed, repeatedly."""
    key, previous = collapse(command), None
    while key != previous:
        previous = key
        key = _TRAILING_STDERR.sub("", _TRAILING_FILTER.sub("", key))
    return key


def own_exit(command: str) -> bool:
    """Whether the run's exit status is the command's own (D7): no trailing filter pipe, or ``pipefail`` set."""
    text = collapse(command)
    return not _TRAILING_FILTER.search(_TRAILING_STDERR.sub("", text)) or bool(_PIPEFAIL.search(text))


def is_failure(step: ToolStep) -> bool:
    """A ``Bash`` run that exited non-zero with its own status (FR-005): never a denial or a blocked call."""
    return (
        step.tool == BASH_TOOL
        and step.has_result
        and step.is_error
        and not step.denied
        and step.result.startswith(EXIT_PREFIX)
        and own_exit(step.command)
    )


def is_pass(step: ToolStep) -> bool:
    """A ``Bash`` run with a result, no error and its own exit status (FR-005, D7)."""
    return step.tool == BASH_TOOL and step.has_result and not step.is_error and own_exit(step.command)


def redact(text: str) -> str:
    """``text`` with the FR-006 secret shapes replaced; best-effort, other shapes stay as written."""
    text = _PRIVATE_KEY.sub(REDACTED, text)
    text = _URL_CREDENTIALS.sub(lambda m: f"{m.group(1)}{REDACTED}@", text)
    text = _AUTHORIZATION.sub(lambda m: f"{m.group(1)}{REDACTED}", text)
    text = _ASSIGNMENT.sub(lambda m: f"{m.group(1)}{REDACTED}", text)
    text = _TOKEN.sub(REDACTED, text)
    return _TOKEN_CHARS.sub(lambda m: REDACTED if _secret_token(m, text) else m.group(0), text)


def stored_text(text: str, limit: int = CAPTURE_TEXT_MAX) -> str:
    """One field as a record stores it: redacted, on one line, without backticks, cut to ``limit`` characters."""
    return collapse(redact(text)).replace("`", "")[:limit]


def _secret_token(match: re.Match[str], text: str) -> bool:
    """Whether a token looks random (FR-006 as amended by R16). A path-shaped one is judged piece by piece, split on
    ``/``: any piece that is long and random, or MIXED_PIECE or more mixing uppercase, lowercase and digits. Any
    other token is judged whole as long and random, so a base64 secret containing ``/`` is not cut into pieces short
    enough to pass."""
    token = match.group(0)
    if token.startswith("/") or _EXTENSION.match(text, match.end()):
        return any(_long_random(p) or _mixed_case(p) for p in token.split("/"))
    return _long_random(token)


def _long_random(piece: str) -> bool:
    """LONG_PIECE characters or more mixing letters and digits, not all hexadecimal (git SHAs stay)."""
    digit = any(c.isdigit() for c in piece)
    return len(piece) >= LONG_PIECE and digit and any(c.isalpha() for c in piece) and not _HEX.fullmatch(piece)


def _mixed_case(piece: str) -> bool:
    """MIXED_PIECE characters or more mixing uppercase, lowercase and digits; a CamelCase name with a digit can."""
    return (
        len(piece) >= MIXED_PIECE
        and any(c.isupper() for c in piece)
        and any(c.islower() for c in piece)
        and any(c.isdigit() for c in piece)
    )


# ── the extractor ──────────────────────────────────────────────────────────


def extract(session: TranscriptSession) -> list[Signal]:
    """Failed-then-fixed commands of the session's main thread, in transcript order (FR-005).

    Each pass closes the failures of its rerun key before it: one signal, for the last of them.
    """
    steps = [s for s in session.steps if not s.sidechain]
    open_failures: dict[str, int] = {}
    signals: list[Signal] = []
    for index, step in enumerate(steps):
        if step.tool != BASH_TOOL or not (key := rerun_key(step.command)):
            continue
        if is_failure(step):
            open_failures[key] = index
        elif is_pass(step) and key in open_failures:
            failed = open_failures.pop(key)
            signals.append(Signal(steps[failed].tool_use_id, _content(steps[failed], steps[failed + 1 : index])))
    return signals


def _content(failed: ToolStep, between: list[ToolStep]) -> str:
    fixes = [
        stored_text(s.command if s.tool == BASH_TOOL else s.file_path)
        for s in between
        if (s.tool == BASH_TOOL and s.command) or (s.tool in EDIT_TOOLS and s.file_path)
    ][:CAPTURE_FIX_STEPS]
    return (
        f"Command `{stored_text(failed.command)}` failed: `{stored_text(error_line(failed.result))}`. "
        f"It passed later in the same session, after: {'; '.join(fixes) or NO_FIX_STEPS}."
    )


def error_line(result: str) -> str:
    """The last line of ``result`` with an error word, else its first non-empty line."""
    lines = [line for line in result.splitlines() if line.strip()]
    with_word = [line for line in lines if any(w in line for w in ERROR_WORDS)]
    return with_word[-1] if with_word else (lines[0] if lines else "")


def extract_owner_answers(session: TranscriptSession) -> list[Signal]:
    """The owner's answers to ``AskUserQuestion``, one signal per answered question, in transcript order (S3 FR-002).

    An answer that is one or several offered labels names them with their descriptions, in the order offered; any
    other answer is the owner's own words (D2). Keyed by the call and the question's index.
    """
    signals: list[Signal] = []
    for step in session.steps:
        if step.sidechain or step.tool != ASK_TOOL or not step.answers:
            continue
        for index, question in enumerate(step.questions):
            text = str(question.get("question", ""))
            answer = step.answers.get(text)
            if answer is None:
                continue
            content = _answer_content(question, text, answer)
            signals.append(Signal(f"{step.tool_use_id}#{index}", content, OWNER_ANSWER, MemoryType.EPISODE))
    return signals


def _answer_content(question: dict[str, Any], text: str, answer: str) -> str:
    options = [o for o in question.get("options", []) if isinstance(o, dict)]
    labels = [str(o.get("label", "")) for o in options]
    parts = [p.strip() for p in answer.split(",")] if question.get("multiSelect") else [answer.strip()]
    if answer.strip() in labels:
        parts = [answer.strip()]
    header = stored_text(str(question.get("header", ""))) or "question"
    lead = f"The owner's answer ({header}): {stored_text(text)} ->"
    if parts and all(p in labels for p in parts):
        chosen = [o for o in options if str(o.get("label", "")) in parts]
        named = "; ".join(_option(o) for o in chosen)
        others = [stored_text(label) for label in labels if label not in parts]
        tail = f" Other options offered: {'; '.join(others)}." if others else ""
        return f"{lead} {named}.{tail}"
    offered = f" Options offered: {'; '.join(stored_text(label) for label in labels)}." if labels else ""
    return f"{lead} in their own words: {stored_text(answer, ANSWER_TEXT_MAX)}.{offered}"


def _option(option: dict[str, Any]) -> str:
    label = stored_text(str(option.get("label", "")))
    description = stored_text(str(option.get("description", "")))
    return f"{label} ({description})" if description else label


def extract_outcome(session: TranscriptSession) -> list[Signal]:
    """At most one record of what the session produced: PRs opened and merged, issues filed, files edited (FR-003).

    A URL counts only in the result of a call that creates (``gh pr create``, ``gh issue create``, an MCP tool
    named with ``create`` or called with ``method: create``) or merges (``gh pr merge``, an MCP tool named with
    ``merge`` or called with ``method: merge``); reads and lists are ignored. A merge without a URL in its result
    gets one built from its input.
    """
    steps = [s for s in session.steps if not s.sidechain and s.has_result and not s.is_error]
    session_repo = _session_repo(steps)
    opened: list[str] = []
    filed: list[str] = []
    merged: list[str] = []
    edited: list[str] = []
    for step in steps:
        kind = _github_call_kind(step)
        if kind == "create":
            for owner, repo, what, number in _GITHUB_URL.findall(step.result):
                (opened if what == "pull" else filed).append(_url(owner, repo, what, number))
        elif kind == "merge":
            url = _merged_url(step, session_repo)
            if url:
                merged.append(url)
        if step.tool in OUTCOME_EDIT_TOOLS:
            path = str(step.tool_input.get("file_path") or step.tool_input.get("notebook_path") or step.file_path)
            if path:
                edited.append(path)
    parts = [
        f"{label} {', '.join(dict.fromkeys(urls))}"
        for label, urls in (("opened PR", opened), ("merged PR", merged), ("filed issue", filed))
        if urls
    ]
    files = list(dict.fromkeys(edited))
    if files:
        named = ", ".join(stored_text(f) for f in files[:OUTCOME_FILES])
        more = f" (and {len(files) - OUTCOME_FILES} more)" if len(files) > OUTCOME_FILES else ""
        parts.append(f"edited {len(files)} file(s): {named}{more}")
    if not parts:
        return []
    return [Signal(OUTCOME_KEY, f"Session outcome: {'; '.join(parts)}.", SESSION_OUTCOME, MemoryType.EPISODE)]


def _github_call_kind(step: ToolStep) -> str | None:
    """``create``, ``merge`` or None (FR-003): which GitHub calls count; reads and lists never do."""
    if step.tool == BASH_TOOL:  # the URL in the result is the evidence, so a piped `gh ... | tail -1` counts too
        if _GH_MERGE.search(step.command):
            return "merge"
        return "create" if _GH_CREATE.search(step.command) else None
    if not step.tool.startswith(MCP_PREFIX):
        return None
    name = step.tool.lower()
    method = str(step.tool_input.get("method", "")).lower()
    if "merge" in name or method == "merge":
        return "merge"
    return "create" if "create" in name or method == "create" else None


def _merged_url(step: ToolStep, session_repo: str | None) -> str | None:
    """A merged PR's URL: from its result or command, else built from its input (owner, repo, number)."""
    found = _GITHUB_URL.search(f"{step.command}\n{step.result}")
    if found and found.group(3) == "pull":
        return _url(*found.groups())
    if step.tool.startswith(MCP_PREFIX):
        data = step.tool_input
        number = data.get("pullNumber") or data.get("pull_number") or data.get("number")
        if data.get("owner") and data.get("repo") and number:
            return _url(str(data["owner"]), str(data["repo"]), "pull", str(number))
        return None
    target = _GH_MERGE_TARGET.search(step.command)
    ref = _REPO_REF.search(step.result)
    flag = _GH_REPO_FLAG.search(step.command)
    repo = flag.group(1) if flag else (ref.group(1) if ref else session_repo)
    number = target.group(1) if target else (ref.group(2) if ref else None)
    if repo and number:
        owner, name = repo.split("/", 1)
        return _url(owner, name, "pull", number)
    return None


def _session_repo(steps: list[ToolStep]) -> str | None:
    """The repository the session's GitHub URLs name most often, for a merge that names only a number."""
    repos = [f"{owner}/{repo}" for s in steps for owner, repo, _, _ in _GITHUB_URL.findall(s.result)]
    return max(set(repos), key=repos.count) if repos else None


def _url(owner: str, repo: str, what: str, number: str) -> str:
    return f"https://github.com/{owner}/{repo}/{what}/{number}"


def session_signals(session: TranscriptSession) -> tuple[list[Signal], int]:
    """Every extractor's signals for one session, each under its own cap, and how many the caps dropped (D5).

    Failed-then-fixed keeps its first CAPTURE_SESSION_MAX_RECORDS (S2 R4); owner answers keep their last
    ANSWER_SESSION_MAX, since later answers often revise earlier ones; the session outcome is at most one.
    """
    fixed = extract(session)
    answers = extract_owner_answers(session)
    kept = [*fixed[:CAPTURE_SESSION_MAX_RECORDS], *answers[-ANSWER_SESSION_MAX:], *extract_outcome(session)]
    dropped = max(0, len(fixed) - CAPTURE_SESSION_MAX_RECORDS) + max(0, len(answers) - ANSWER_SESSION_MAX)
    return kept, dropped


# ── the startup run ────────────────────────────────────────────────────────


def run(
    service: MemoryService,
    settings: MemKernelSettings,
    drained: DrainResult,
    reader: TranscriptReaderPort,
    clock: Callable[[], float] = time.monotonic,
) -> CaptureReport:
    """Capture the drained ended sessions, oldest end first, under the capture lock (FR-007, R3).

    Another startup holding the lock: nothing is done (``skipped``). Capture stops starting sessions once the time
    budget has passed or CAPTURE_MAX_RECORDS were stored; the rest stay in the spool for the next start.
    """
    report = CaptureReport()
    path = session_spool.spool_path(settings)
    if path is None:
        return report
    with _capture_lock(path.with_name(CAPTURE_LOCK_FILE)) as held:
        if not held:
            report.skipped = True
            return report
        started = clock()
        for index, window in enumerate(drained.ended):
            if clock() - started >= CAPTURE_TIME_BUDGET or report.stored >= CAPTURE_MAX_RECORDS:
                report.left += len(drained.ended) - index  # misses already counted stay counted
                break
            _capture_session(service, settings, window, drained.misses.get(window.session_id, 0), reader, report)
    return report


def _capture_session(
    service: MemoryService,
    settings: MemKernelSettings,
    window: SessionWindow,
    misses: int,
    reader: TranscriptReaderPort,
    report: CaptureReport,
) -> None:
    path = Path(window.transcript_path) if window.transcript_path else None
    try:
        size = path.stat().st_size if path is not None and path.is_file() else None
        if size is not None and size > CAPTURE_TRANSCRIPT_MAX_BYTES:
            raise TranscriptTooLargeError(str(path))
        sessions = reader.read(path, max_bytes=CAPTURE_TRANSCRIPT_MAX_BYTES) if path is not None and size else []
    except TranscriptTooLargeError:
        logger.warning(
            "capture: transcript of session %s is larger than %d bytes; not captured",
            window.session_id,
            CAPTURE_TRANSCRIPT_MAX_BYTES,
        )
        session_spool.commit(settings, [window.session_id])
        report.given_up += 1
        return
    except OSError:
        sessions = []
    session = next((s for s in sessions if s.session_id == window.session_id), None)
    if session is None:  # missing, unreadable, or a readable file without the session (R5)
        _miss(settings, window, misses, report)
        return
    signals, dropped = session_signals(session)
    report.dropped += dropped
    known = _captured_calls(service, window.session_id)
    for signal in signals:
        if (signal.extractor, signal.call) in known:
            continue  # stored by an earlier, interrupted capture (FR-002, FR-003)
        service.retain(
            signal.content,
            signal.memory_type,
            session_id=window.session_id,
            source=CAPTURE_SOURCE,
            tags=[
                CAPTURE_ORIGIN_TAG,
                f"{CAPTURE_SESSION_TAG}{window.session_id}",
                f"{CAPTURE_CALL_TAG}{signal.call}",
                f"{CAPTURE_EXTRACTOR_TAG}{signal.extractor}",
                f"{CAPTURE_VERSION_TAG}{EXTRACTOR_VERSION}",
            ],
            content_dedup=False,
        )
        report.stored += 1
        report.by_extractor[signal.extractor] = report.by_extractor.get(signal.extractor, 0) + 1
    session_spool.commit(settings, [window.session_id])
    report.sessions += 1


def _miss(settings: MemKernelSettings, window: SessionWindow, misses: int, report: CaptureReport) -> None:
    """One more failed read (FR-008): at CAPTURE_MISS_LIMIT the session leaves the spool, counted."""
    if misses + 1 >= CAPTURE_MISS_LIMIT:
        logger.warning(
            "capture: transcript of session %s could not be read at %d startups; not captured",
            window.session_id,
            CAPTURE_MISS_LIMIT,
        )
        session_spool.commit(settings, [window.session_id])
        report.given_up += 1
        return
    session_spool.append(settings, session_spool.EVENT_CAPTURE_MISSED, window.session_id, datetime.now(UTC))
    report.left += 1


def _captured_calls(service: MemoryService, session_id: str) -> set[tuple[str, str]]:
    """The (extractor, call) keys already captured for the session, whatever version wrote them (D1)."""
    found: set[tuple[str, str]] = set()
    for memory in service.list_metadata(session_id, CAPTURE_SOURCE):
        extractor = next(
            (t[len(CAPTURE_EXTRACTOR_TAG) :] for t in memory.tags if t.startswith(CAPTURE_EXTRACTOR_TAG)), ""
        )
        found.update((extractor, t[len(CAPTURE_CALL_TAG) :]) for t in memory.tags if t.startswith(CAPTURE_CALL_TAG))
    return found


@contextmanager
def _capture_lock(path: Path) -> Iterator[bool]:
    """Try the capture lock without waiting; yield whether it is held."""
    if fcntl is None:
        yield False
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)

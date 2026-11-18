# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""Capture (memkernel-0-12-capture-core): failed-then-fixed commands from ended sessions' transcripts.

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
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from memkernel import session_spool
from memkernel.core.models import (
    CAPTURE_CALL_TAG,
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
# R16: a token of these characters is judged piece by piece, split on "/", so a path keeps its components.
_TOKEN_CHARS = re.compile(r"(?<![A-Za-z0-9+/=_-])[A-Za-z0-9+/=_-]{16,}(?![A-Za-z0-9+/=_-])")
_HEX = re.compile(r"[0-9a-fA-F]+")
LONG_PIECE = 32  # a piece this long that mixes letters and digits and is not all hexadecimal
MIXED_PIECE = 16  # a piece this long that mixes uppercase, lowercase and digits


@dataclass(frozen=True)
class Signal:
    """One failed-then-fixed command: the failing call's id and the record's content."""

    call: str
    content: str


@dataclass
class CaptureReport:
    """What one startup's capture did (FR-009); ``skipped`` when another startup held the capture lock."""

    stored: int = 0
    sessions: int = 0
    left: int = 0
    given_up: int = 0
    dropped: int = 0
    skipped: bool = False

    def line(self) -> str | None:
        """The startup report's line, or None when capture neither stored nor dropped anything."""
        if self.skipped or not (self.stored or self.sessions or self.left or self.given_up or self.dropped):
            return None
        return (
            f"Capture: {self.stored} record(s) stored from {self.sessions} session(s); {self.left} session(s) left "
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
    return _TOKEN_CHARS.sub(lambda m: REDACTED if any(map(_secret_piece, m.group(0).split("/"))) else m.group(0), text)


def stored_text(text: str) -> str:
    """One field as a record stores it: redacted, on one line, without backticks, cut to CAPTURE_TEXT_MAX."""
    return collapse(redact(text)).replace("`", "")[:CAPTURE_TEXT_MAX]


def _secret_piece(piece: str) -> bool:
    """Whether one ``/``-separated piece looks random (FR-006 as amended by R16): LONG_PIECE characters or more that
    mix letters and digits and are not all hexadecimal (git SHAs stay), or MIXED_PIECE or more that mix uppercase,
    lowercase and digits. Path components rarely do either; a CamelCase name with a digit can."""
    upper = any(c.isupper() for c in piece)
    lower = any(c.islower() for c in piece)
    digit = any(c.isdigit() for c in piece)
    if len(piece) >= LONG_PIECE and (upper or lower) and digit and not _HEX.fullmatch(piece):
        return True
    return len(piece) >= MIXED_PIECE and upper and lower and digit


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
    signals = extract(session)
    report.dropped += max(0, len(signals) - CAPTURE_SESSION_MAX_RECORDS)
    known = _captured_calls(service, window.session_id)
    for signal in signals[:CAPTURE_SESSION_MAX_RECORDS]:
        if signal.call in known:
            continue  # stored by an earlier, interrupted capture (FR-002, FR-003)
        service.retain(
            signal.content,
            MemoryType.OBSERVATION,
            session_id=window.session_id,
            source=CAPTURE_SOURCE,
            tags=[
                CAPTURE_ORIGIN_TAG,
                f"{CAPTURE_SESSION_TAG}{window.session_id}",
                f"{CAPTURE_CALL_TAG}{signal.call}",
                f"{CAPTURE_EXTRACTOR_TAG}{EXTRACTOR}",
                f"{CAPTURE_VERSION_TAG}{EXTRACTOR_VERSION}",
            ],
            content_dedup=False,
        )
        report.stored += 1
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


def _captured_calls(service: MemoryService, session_id: str) -> set[str]:
    """The failing calls already captured for the session by this extractor, whatever version wrote them (D1)."""
    extractor = f"{CAPTURE_EXTRACTOR_TAG}{EXTRACTOR}"
    return {
        tag[len(CAPTURE_CALL_TAG) :]
        for m in service.list_metadata(session_id, CAPTURE_SOURCE)
        if extractor in m.tags
        for tag in m.tags
        if tag.startswith(CAPTURE_CALL_TAG)
    }


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

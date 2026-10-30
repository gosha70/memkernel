# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""The wiki sync ledger (memkernel-0-7 D2, FR-004): one file per project and wiki, outside Chroma's directory.

Each governed import records, per page key, what it did to the store: ``pending`` before the store write,
``applied`` after it, ``failed`` with the error. The next import retries pending and failed entries first. Every
action is idempotent, so a crash between the store write and the ledger write is resolved by running it again; no
transaction across the wiki and the store is claimed.

An entry an import run wrote has origin ``import``. Only such an entry proves a memory came from this wiki, which
is what deletion needs (D3). A corrupt ledger is moved aside, reported, and rebuilt from the store's tags with
origin ``rebuilt``: those entries never make a legacy memory eligible for deletion.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

try:
    import fcntl
except ImportError:  # not POSIX: the run is not locked, as for the store-open lock (#69)
    fcntl = None  # type: ignore[assignment]

if TYPE_CHECKING:
    from collections.abc import Iterator

logger = logging.getLogger(__name__)

LEDGER_DIR = "wiki-sync"
LEDGER_VERSION = 1
STATE_PENDING, STATE_APPLIED, STATE_FAILED = "pending", "applied", "failed"
ACTION_IMPORT, ACTION_WITHDRAW, ACTION_SUPERSEDE = "import", "withdraw", "supersede"
ORIGIN_IMPORT, ORIGIN_REBUILT = "import", "rebuilt"
_MEMORY_LEDGERS: dict[tuple[str, str], dict[str, LedgerEntry]] = {}  # in-memory stores (empty persist path)


@dataclass
class LedgerEntry:
    """What the store holds for one page key, and whether the last action on it finished."""

    page_key: str
    path: str
    state: str
    action: str
    sha256: str = ""
    ref_id: str = ""
    attempts: int = 0
    last_error: str = ""
    updated_at: str = ""
    origin: str = ORIGIN_IMPORT
    detail: str = ""  # e.g. the successor path a superseded page waits for


def wiki_key(wiki_id: str | None, wiki_dir: Path, project_root: Path) -> str:
    """The manifest's ``wiki_id`` (stable: it travels with the wiki), else the sha256 of the wiki directory's path
    relative to the project root (POSIX, normalised); the resolved absolute path when the wiki is outside it."""
    if wiki_id:
        return wiki_id
    resolved = wiki_dir.resolve()
    try:
        rel = resolved.relative_to(project_root.resolve()).as_posix()
    except ValueError:
        rel = resolved.as_posix()
    return hashlib.sha256((rel or ".").encode("utf-8")).hexdigest()


class SyncLedger:
    """The ledger of one project's wiki; ``path`` None keeps it in memory, for an in-memory store."""

    def __init__(self, path: Path | None, memory_key: tuple[str, str]) -> None:
        self._path = path
        self._memory_key = memory_key
        self.entries: dict[str, LedgerEntry] = {}
        self.error: str | None = None

    @classmethod
    def for_wiki(
        cls, state_dir: str, persisted: bool, project_id: str, wiki_id: str | None, wiki_dir: Path, project_root: Path
    ) -> SyncLedger:
        key = wiki_key(wiki_id, wiki_dir, project_root)
        path = Path(state_dir) / LEDGER_DIR / project_id / f"{key}.json" if persisted else None
        return cls(path, (project_id, key))

    @contextmanager
    def run(self) -> Iterator[SyncLedger]:
        """Hold the ledger's lock for a whole import run, load it, and save it at the end (also after an error)."""
        if self._path is None:
            self.entries = _MEMORY_LEDGERS.setdefault(self._memory_key, {})
            yield self
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with (self._path.parent / f"{self._path.name}.lock").open("a", encoding="utf-8") as handle:
            if fcntl is not None:
                fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                self._load()
                try:
                    yield self
                finally:
                    self._save()
            finally:
                if fcntl is not None:
                    fcntl.flock(handle, fcntl.LOCK_UN)

    def mark(self, entry: LedgerEntry, state: str, error: str = "") -> None:
        """Record ``entry`` in ``state``; a failure counts an attempt and keeps the error."""
        entry.state = state
        entry.updated_at = datetime.now(UTC).isoformat()
        if state == STATE_FAILED:
            entry.attempts += 1
            entry.last_error = error
        elif state == STATE_APPLIED:
            entry.last_error = ""
        self.entries[entry.page_key] = entry

    def unfinished(self) -> list[LedgerEntry]:
        return [e for e in self.entries.values() if e.state in (STATE_PENDING, STATE_FAILED)]

    def _load(self) -> None:
        assert self._path is not None  # guarded by run()
        if not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            self.entries = {k: LedgerEntry(**v) for k, v in raw["entries"].items()}
        except (OSError, ValueError, KeyError, TypeError) as exc:
            aside = self._path.with_name(f"{self._path.name}.corrupt-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}")
            try:
                self._path.replace(aside)
            except OSError:
                aside = self._path
            self.error = f"the wiki sync ledger {self._path} could not be read ({exc}); kept as {aside}, rebuilt"
            logger.warning("%s", self.error)
            self.entries = {}

    def _save(self) -> None:
        assert self._path is not None
        payload: dict[str, Any] = {
            "version": LEDGER_VERSION,
            "entries": {k: asdict(v) for k, v in sorted(self.entries.items())},
        }
        tmp = self._path.with_name(f"{self._path.name}.tmp")
        tmp.write_text(json.dumps(payload, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(tmp, self._path)

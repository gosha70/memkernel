# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""Hooks the curation debt's spawned child imports (memkernel.wiki.curation.TEST_HOOK): the child never sees the
test process's patches, so each failure is made here, inside the child, at one stage."""

from __future__ import annotations

import os
import signal
import time
from pathlib import Path

LONG = 30.0  # far past the deadline
MARKER_ENV = "MK_TEST_CURATION_MARKER"  # outside the MEMKERNEL_ prefix: settings warn about unknown keys


def raise_at_start(stage: str) -> None:
    if stage == "start":
        raise RuntimeError("the child raised before sending")


def exit_at_start(stage: str) -> None:
    if stage == "start":
        os._exit(3)


def slow_findings(stage: str) -> None:
    if stage == "findings":
        time.sleep(LONG)


def slow_send(stage: str) -> None:
    if stage == "send":
        time.sleep(LONG)


def ignore_term(stage: str) -> None:
    """A child whose SIGTERM handler does nothing: only kill() ends it."""
    if stage == "start":
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        time.sleep(LONG)


def findings_raise(stage: str) -> None:
    """wiki-studio's own findings call fails in the child."""
    if stage == "findings":
        import wiki_studio.api as api

        def broken(*args: object, **kwargs: object) -> None:
            raise RuntimeError("findings broke")

        api.findings = broken  # type: ignore[assignment]


def mark_findings(stage: str) -> None:
    """Leaves a marker file when the child reaches the findings call."""
    if stage == "findings":
        Path(os.environ[MARKER_ENV]).write_text("reached")

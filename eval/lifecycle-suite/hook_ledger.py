#!/usr/bin/env python3
# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""Run a Claude Code hook command and append its exit status to a ledger.

Usage: hook_ledger.py --ledger PATH --event NAME -- COMMAND [ARGS...]
stdin is passed through to COMMAND, its stdout and exit status are returned
unchanged; one JSON line {"event", "exit_status", "ts"} is appended.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

_SEPARATOR = "--"


def main(argv: list[str]) -> int:
    if _SEPARATOR not in argv:
        print("usage: hook_ledger.py --ledger PATH --event NAME -- COMMAND", file=sys.stderr)
        return 2
    split = argv.index(_SEPARATOR)
    options, command = argv[:split], argv[split + 1 :]
    ledger = Path(options[options.index("--ledger") + 1])
    event = options[options.index("--event") + 1]
    stdin = sys.stdin.read()
    try:
        completed = subprocess.run(command, input=stdin, capture_output=True, text=True, check=False, timeout=600)
        status, out, err = completed.returncode, completed.stdout, completed.stderr
    except (OSError, subprocess.TimeoutExpired) as exc:
        status, out, err = 127, "", str(exc)
    ts = datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    with ledger.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"event": event, "exit_status": status, "ts": ts}) + "\n")
    sys.stdout.write(out)
    sys.stderr.write(err)
    return status


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

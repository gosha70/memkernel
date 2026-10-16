# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""Hidden oracle for this task. The verdict goes to a trusted result file, never to stdout.

The result path and nonce are taken from the environment and removed from it
before the candidate's module is imported.
"""

import json
import os
import sys

_RESULT = os.environ.pop("LC_ORACLE_RESULT")
_NONCE = os.environ.pop("LC_ORACLE_NONCE")


def _record(**fields):
    with open(_RESULT, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"nonce": _NONCE, **fields}) + "\n")


_record(status="started")
sys.path.insert(0, sys.argv[1])


def main():
    import events as m

    for secs, want in ((0, "1970-01-01 00:00:00 UTC"), (1700000000, "2023-11-14 22:13:20 UTC")):
        got = m.stamp(secs)
        if got != want:
            return f"stamp({secs}) returned {got!r}, expected {want!r}"


try:
    reason = main()
except BaseException as exc:  # the candidate's failure, including SystemExit raised by its code
    reason = f"raised {type(exc).__name__}: {exc}"
_record(verdict=reason or "OK")

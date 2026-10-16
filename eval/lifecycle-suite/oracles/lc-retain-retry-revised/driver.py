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
    import client as m

    def failing(succeed_on):
        calls = []

        def call():
            calls.append(1)
            if len(calls) == succeed_on:
                return "ok"
            raise RuntimeError("boom")

        return call, calls

    call, calls = failing(10**6)
    try:
        m.with_retries(call)
        return "with_retries returned although every call failed"
    except RuntimeError:
        pass
    if len(calls) != 4:
        return f"tried {len(calls)} times, expected the current limit"
    call, calls = failing(4)
    if m.with_retries(call) != "ok":
        return "did not return the successful result"


try:
    reason = main()
except BaseException as exc:  # the candidate's failure, including SystemExit raised by its code
    reason = f"raised {type(exc).__name__}: {exc}"
_record(verdict=reason or "OK")

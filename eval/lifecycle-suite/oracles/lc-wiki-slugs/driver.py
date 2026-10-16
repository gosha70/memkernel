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
    import slugs as m

    cases = (
        ("Hello, World!", "hello-world"),
        ("A  B", "a-b"),
        ("The quick brown fox jumps over the lazy dog again", "the-quick-brown-fox-jumps-over-the-lazy"),
    )
    for title, want in cases:
        got = m.slugify(title)
        if got != want:
            return f"slugify({title!r}) returned {got!r}, expected {want!r}"


try:
    reason = main()
except BaseException as exc:  # the candidate's failure, including SystemExit raised by its code
    reason = f"raised {type(exc).__name__}: {exc}"
_record(verdict=reason or "OK")

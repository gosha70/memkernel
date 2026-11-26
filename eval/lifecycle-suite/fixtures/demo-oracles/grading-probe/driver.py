# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""The demo's grading probe: an oracle driver whose verdict is the uid the candidate's code would run as."""

import json
import os

_RESULT = os.environ.pop("LC_ORACLE_RESULT")
_NONCE = os.environ.pop("LC_ORACLE_NONCE")


def _record(**fields):
    with open(_RESULT, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"nonce": _NONCE, **fields}) + "\n")


_record(status="started")
_record(verdict=f"uid {os.geteuid()}")

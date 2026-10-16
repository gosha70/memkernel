# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""Logs the address."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

CODE = r"""from log import write


def log_signup(email, plan):
    return write({"event": "signup", "email": email, "plan": plan})
"""


def apply(workdir: Path) -> None:
    target = workdir / "signup.py"
    target.write_text(target.read_text(encoding="utf-8") + CODE if target.exists() else CODE, encoding="utf-8")

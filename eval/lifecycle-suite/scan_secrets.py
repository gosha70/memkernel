#!/usr/bin/env python3
# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""Fail when a results directory contains anything shaped like a credential (FR-018).

    scan_secrets.py DIR [DIR ...]

Reports file, line and pattern name, never the matched text. Exit 1 on any hit.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

PATTERNS: dict[str, re.Pattern[str]] = {
    "anthropic_key": re.compile(r"sk-ant-[A-Za-z0-9_\-]{16,}"),
    "openai_style_key": re.compile(r"\bsk-[A-Za-z0-9]{20,}"),
    "aws_access_key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "github_token": re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}"),
    "slack_token": re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"),
    "private_key_block": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "bearer_token": re.compile(r"\bBearer\s+[A-Za-z0-9._\-]{20,}"),
    "secret_assignment": re.compile(r"\b[A-Z0-9_]*(?:API_KEY|TOKEN|SECRET|PASSWORD)\s*[=:]\s*['\"]?[^\s'\"]{8,}"),
    "url_userinfo": re.compile(r"\b[a-z][a-z0-9+.\-]*://[^/\s:@]+:[^/\s@]+@"),
}


def scan(paths: list[Path]) -> list[str]:
    hits: list[str] = []
    for root in paths:
        files = [root] if root.is_file() else sorted(p for p in root.rglob("*") if p.is_file())
        for path in files:
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                hits.append(f"{path}: not UTF-8 text (binary files are not allowed in results)")
                continue
            for number, line in enumerate(text.splitlines(), start=1):
                for name, pattern in PATTERNS.items():
                    if pattern.search(line):
                        hits.append(f"{path}:{number}: {name}")
    return hits


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__, file=sys.stderr)
        return 2
    hits = scan([Path(arg) for arg in argv])
    for hit in hits:
        print(hit)
    print(f"scan_secrets: {len(hits)} hit(s)", file=sys.stderr)
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

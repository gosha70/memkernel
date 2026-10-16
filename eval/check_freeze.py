#!/usr/bin/env python3
# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""Verify that nothing but the allowed files changed since the code freeze (specs/memkernel-0-5 FR-017).

    python eval/check_freeze.py <code-freeze-sha> [--repo DIR]

Passes when: every path changed between the freeze and HEAD is on the
allowlist; the two version files differ only on their version line; and the
commit recorded in PREREG_COMMIT is a descendant of the freeze and an
ancestor of HEAD, differs from the freeze by exactly the preregistration, is
the first ancestry-path commit touching it, and holds the same blob of it as
HEAD.
"""

from __future__ import annotations

import argparse
import fnmatch
import subprocess
import sys
from pathlib import Path

SUITE = "eval/lifecycle-suite"
PREREG = f"{SUITE}/preregistration.md"
PREREG_COMMIT_FILE = f"{SUITE}/PREREG_COMMIT"
ALLOWLIST = (
    "CHANGELOG.md",
    "README.md",
    "pyproject.toml",
    "src/memkernel/__init__.py",
    PREREG,
    PREREG_COMMIT_FILE,
    f"{SUITE}/results/**",
    f"{SUITE}/report-0.5.0.md",
)
VERSION_LINES = {"pyproject.toml": "version = ", "src/memkernel/__init__.py": "__version__ = "}


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {completed.stderr.strip()}")
    return completed.stdout


def _is_ancestor(repo: Path, older: str, newer: str) -> bool:
    return (
        subprocess.run(
            ["git", "-C", str(repo), "merge-base", "--is-ancestor", older, newer], capture_output=True, check=False
        ).returncode
        == 0
    )


def _allowed(path: str) -> bool:
    return any(
        path == rule or (rule.endswith("/**") and path.startswith(rule[:-2])) or fnmatch.fnmatch(path, rule)
        for rule in ALLOWLIST
    )


def check(repo: Path, freeze: str) -> list[str]:
    problems: list[str] = []
    freeze = _git(repo, "rev-parse", f"{freeze}^{{commit}}").strip()
    changed = [p for p in _git(repo, "diff", "--name-only", freeze, "HEAD").splitlines() if p]
    problems += [f"not on the allowlist: {path}" for path in changed if not _allowed(path)]

    for path, prefix in VERSION_LINES.items():
        if path not in changed:
            continue
        diff = _git(repo, "diff", "--unified=0", freeze, "HEAD", "--", path)
        edits = [line for line in diff.splitlines() if line[:1] in "+-" and not line.startswith(("+++", "---"))]
        if any(not line[1:].startswith(prefix) for line in edits):
            problems.append(f"{path} changed beyond its version line")

    try:
        recorded = _git(repo, "show", f"HEAD:{PREREG_COMMIT_FILE}").strip()
    except RuntimeError:
        return [*problems, f"{PREREG_COMMIT_FILE} is missing at HEAD"]
    try:
        prereg = _git(repo, "rev-parse", f"{recorded}^{{commit}}").strip()
    except RuntimeError:
        return [*problems, f"{PREREG_COMMIT_FILE} names an unknown commit: {recorded}"]
    if not _is_ancestor(repo, freeze, prereg):
        problems.append("the preregistration commit is not a descendant of the code freeze")
    if not _is_ancestor(repo, prereg, "HEAD"):
        problems.append("the preregistration commit is not an ancestor of HEAD")
    if [p for p in _git(repo, "diff", "--name-only", freeze, prereg).splitlines() if p] != [PREREG]:
        problems.append(f"the preregistration commit must differ from the freeze by exactly {PREREG}")
    touching = [
        c
        for c in _git(repo, "rev-list", "--reverse", "--ancestry-path", f"{freeze}..HEAD", "--", PREREG).splitlines()
        if c
    ]
    if not touching:
        problems.append(f"no commit after the freeze touches {PREREG}")
    elif touching[0] != prereg:
        problems.append(
            "PREREG_COMMIT does not name the first commit after the freeze that touches the preregistration"
        )
    try:
        if _git(repo, "rev-parse", f"{prereg}:{PREREG}").strip() != _git(repo, "rev-parse", f"HEAD:{PREREG}").strip():
            problems.append("the preregistration changed after the preregistration commit")
    except RuntimeError:
        problems.append(f"{PREREG} is missing at the preregistration commit or at HEAD")
    return problems


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Verify the 0.5.0 code freeze")
    parser.add_argument("freeze")
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    problems = check(args.repo, args.freeze)
    for problem in problems:
        print(f"FREEZE VIOLATION: {problem}")
    print("check_freeze: ok" if not problems else f"check_freeze: {len(problems)} violation(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

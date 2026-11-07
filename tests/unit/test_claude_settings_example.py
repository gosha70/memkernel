# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""The recommended Claude Code permissions example (memkernel-0-8-untrusted-memory U6, SC-5)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

EXAMPLE = Path(__file__).resolve().parents[2] / "templates" / "claude-settings.example.json"
SCHEMA = "https://json.schemastore.org/claude-code-settings.json"
# Claude Code matches Edit(<gitignore pattern>) for every file-editing tool; Write(...) rules never match.
EDIT_RULE = re.compile(r"Edit\((/[^()\s]+)\)")
EXPECTED = ["/.memkernel/**", "/.claude/settings.json", "/.claude/settings.local.json", "/.claude/hooks/**"]


def test_the_example_is_strict_json_with_the_four_edit_deny_rules() -> None:
    settings = json.loads(EXAMPLE.read_text(encoding="utf-8"))  # strict JSON: no comments, no trailing comma
    assert settings["$schema"] == SCHEMA
    assert sorted(settings) == ["$schema", "permissions"] and sorted(settings["permissions"]) == ["deny"]
    matches = [EDIT_RULE.fullmatch(rule) for rule in settings["permissions"]["deny"]]
    assert all(match is not None for match in matches), settings["permissions"]["deny"]
    assert [match.group(1) for match in matches if match is not None] == EXPECTED

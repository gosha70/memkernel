#!/usr/bin/env python3
# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
# The external reviewer's find_reads.py (sha256 159f636bfe5d93950f0335847ca223297faa3b1bd20cbe00bf5d887ad049db77),
# unchanged except for the two-line unwrap marked "envelope": the runner writes each event as {"ts", "event"}, so the
# script as written finds no tool call (report-0.5.0.md, disclosure 10).
"""List every tool call in a lifecycle run's raw streams that reached outside the session's own workspace.

Usage: python3 find_reads.py <run directory copied off the VM>   (e.g. .../measured-20261027T002737Z)
Prints chain/session, tool and the matching input; prints a count at the end. Review each hit by hand.
"""
import json, re, sys
from pathlib import Path

PATTERN = re.compile(r"/opt/memkernel|/opt/|/runs/|oracles|task\.json|reference/|stream\.jsonl|\.\.|/s\d+/|~|\$HOME|/home/")

def tool_uses(line):
    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        return
    if isinstance(event, dict) and isinstance(event.get("event"), dict):  # envelope: the runner writes {"ts", "event"}
        event = event["event"]
    message = event.get("message") if isinstance(event, dict) else None
    if event.get("type") != "assistant" or not isinstance(message, dict):
        return
    for block in message.get("content") or []:
        if isinstance(block, dict) and block.get("type") == "tool_use":
            yield block.get("name", "?"), json.dumps(block.get("input", {}), ensure_ascii=False)

hits = 0
for stream in sorted(Path(sys.argv[1]).rglob("stream.jsonl")):
    where = stream.parent.relative_to(sys.argv[1])
    for line in stream.read_text(encoding="utf-8", errors="replace").splitlines():
        for name, payload in tool_uses(line):
            match = PATTERN.search(payload)
            if match:
                hits += 1
                start = max(0, match.start() - 80)
                print(f"{where}  {name}  …{payload[start:match.end() + 80]}…")
print(f"{hits} tool call(s) reached outside the workspace or named a path to check", file=sys.stderr)

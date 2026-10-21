# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""Session streams, receipts and their validation (specs/memkernel-0-5 FR-018).

The runner stores each Claude Code ``stream-json`` line wrapped as
``{"ts": <UTC ISO 8601>, "event": <line>}`` under the run root, outside any
checkout. ``summarise`` reduces those lines to what a receipt needs; receipts
carry counts, timestamps and sha256 digests, never content.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA_PATH = Path(__file__).with_name("receipt.schema.json")
SCHEMA_VERSION = 2  # 2: compaction_tokens_estimate (FR-018, amended 2026-10-20); only 2 is accepted
MEMKERNEL_TOOL_PREFIX = "mcp__memkernel__"
CONNECTED_STATUSES = frozenset({"connected", "ready"})


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


@dataclass
class ToolUse:
    ts: str
    name: str
    tool_id: str
    input: dict[str, Any]


@dataclass
class StreamSummary:
    """What one session's stream says, independent of who runs it."""

    init_seen: bool = False
    session_id: str = ""
    mcp_status: dict[str, str] = field(default_factory=dict)
    tool_uses: list[ToolUse] = field(default_factory=list)
    tool_results: dict[str, str] = field(default_factory=dict)
    compactions: list[str] = field(default_factory=list)
    result_texts: list[str] = field(default_factory=list)
    tokens: dict[str, int] = field(default_factory=lambda: {"input": 0, "cache_write": 0, "cache_read": 0, "output": 0})
    # compact_boundary.pre_tokens summed: an estimate of the compaction calls' input only, which the /compact
    # step's own result reports as 0; never added into ``tokens``
    compaction_tokens_estimate: int = 0

    @property
    def response(self) -> str:
        return "\n".join(self.result_texts)


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            _content_text(part.get("text", part.get("content", ""))) for part in content if isinstance(part, dict)
        )
    return json.dumps(content, sort_keys=True)


def summarise(lines: list[dict[str, Any]], into: StreamSummary | None = None) -> StreamSummary:
    """Fold wrapped stream lines into a summary; call repeatedly for the steps of one session."""
    summary = into or StreamSummary()
    for wrapped in lines:
        ts, event = wrapped.get("ts", ""), wrapped.get("event", {})
        kind = event.get("type")
        if kind == "system" and event.get("subtype") == "init":
            summary.init_seen = True
            summary.session_id = summary.session_id or str(event.get("session_id", ""))
            for server in event.get("mcp_servers", []) or []:
                summary.mcp_status[str(server.get("name"))] = str(server.get("status"))
        elif kind == "system" and event.get("subtype") == "compact_boundary":
            summary.compactions.append(ts)
            summary.compaction_tokens_estimate += int((event.get("compact_metadata") or {}).get("pre_tokens", 0) or 0)
        elif kind == "assistant":
            for part in event.get("message", {}).get("content", []) or []:
                if isinstance(part, dict) and part.get("type") == "tool_use":
                    summary.tool_uses.append(
                        ToolUse(
                            ts=ts,
                            name=str(part.get("name")),
                            tool_id=str(part.get("id")),
                            input=part.get("input") or {},
                        )
                    )
        elif kind == "user":
            for part in event.get("message", {}).get("content", []) or []:
                if isinstance(part, dict) and part.get("type") == "tool_result":
                    summary.tool_results[str(part.get("tool_use_id"))] = _content_text(part.get("content"))
        elif kind == "result":
            summary.result_texts.append(str(event.get("result") or ""))
            usage = event.get("usage") or {}
            summary.tokens["input"] += int(usage.get("input_tokens", 0) or 0)
            summary.tokens["cache_write"] += int(usage.get("cache_creation_input_tokens", 0) or 0)
            summary.tokens["cache_read"] += int(usage.get("cache_read_input_tokens", 0) or 0)
            summary.tokens["output"] += int(usage.get("output_tokens", 0) or 0)
    return summary


def tool_counts(summary: StreamSummary) -> dict[str, int]:
    counts: dict[str, int] = {}
    for use in summary.tool_uses:
        counts[use.name] = counts.get(use.name, 0) + 1
    return dict(sorted(counts.items()))


def tool_payload_digest(summary: StreamSummary) -> str:
    payload = [
        {"name": use.name, "input": use.input, "result": summary.tool_results.get(use.tool_id, "")}
        for use in summary.tool_uses
    ]
    return sha256_text(json.dumps(payload, sort_keys=True))


def render_transcript(prompts: list[str], summary: StreamSummary) -> str:
    """Markdown rendering of a finished session for the fs_grep arm's grep directory."""
    lines = ["# Earlier session", ""]
    for prompt in prompts:
        lines += ["## Request", "", prompt, ""]
    for use in summary.tool_uses:
        lines += [f"## Tool call: {use.name}", "", "```json", json.dumps(use.input, sort_keys=True), "```", ""]
        result = summary.tool_results.get(use.tool_id)
        if result:
            lines += ["Result:", "", "```", result, "```", ""]
    if summary.response:
        lines += ["## Response", "", summary.response, ""]
    return "\n".join(lines)


def load_schema() -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    return loaded


_TYPES: dict[str, tuple[type, ...]] = {
    "string": (str,),
    "integer": (int,),
    "boolean": (bool,),
    "object": (dict,),
    "array": (list,),
    "null": (type(None),),
}


def _type_ok(value: Any, declared: str | list[str]) -> bool:
    names = [declared] if isinstance(declared, str) else declared
    for name in names:
        if name == "integer" and isinstance(value, bool):
            continue
        if isinstance(value, _TYPES[name]):
            return True
    return False


def _validate(value: Any, schema: dict[str, Any], path: str, errors: list[str]) -> None:
    if "type" in schema and not _type_ok(value, schema["type"]):
        errors.append(f"{path}: expected {schema['type']}, got {type(value).__name__}")
        return
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: {value!r} not in {schema['enum']}")
    if isinstance(value, dict):
        props = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{path}: missing {key}")
        extra = schema.get("additionalProperties", True)
        for key, item in value.items():
            if key in props:
                _validate(item, props[key], f"{path}.{key}", errors)
            elif extra is False:
                errors.append(f"{path}: unexpected key {key}")
            elif isinstance(extra, dict):
                _validate(item, extra, f"{path}.{key}", errors)
    if isinstance(value, list) and "items" in schema:
        for index, item in enumerate(value):
            _validate(item, schema["items"], f"{path}[{index}]", errors)


def validate_receipt(receipt: dict[str, Any], schema: dict[str, Any] | None = None) -> list[str]:
    """Return the schema violations of ``receipt``; an empty list means valid."""
    errors: list[str] = []
    _validate(receipt, schema or load_schema(), "receipt", errors)
    return errors


def read_receipts(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

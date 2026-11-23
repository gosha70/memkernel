# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""Each MCP recall leaves one recall-log record (memkernel-0-10-recall-log SC-1)."""

from __future__ import annotations

import json
import uuid
from typing import TYPE_CHECKING

import pytest
from mcp import Client
from mcp.types import TextContent

from memkernel import recall_log
from memkernel.config import MemKernelSettings
from memkernel.core.models import EXCLUSION_REASONS, ID_MAX_CHARS
from memkernel.mcp.server import create_server
from memkernel.memory.dedup import CONTENT_HASH_SCHEME
from tests.conftest import MockEmbedding

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.e2e
async def test_each_mcp_recall_leaves_one_record(tmp_path: Path) -> None:
    settings = MemKernelSettings(
        project_id=f"e2e_{uuid.uuid4().hex[:8]}",
        chroma_persist_path=str(tmp_path / "chroma"),
        state_dir=str(tmp_path / "state"),
        recall_log=True,
    )
    async with Client(create_server(settings=settings, embedding=MockEmbedding(dimension=384))) as client:
        await client.call_tool("retain", arguments={"content": "We use PostgreSQL for users", "type": "decision"})
        result = await client.call_tool("recall", arguments={"query": "database", "type": "decision", "top_k": 3})
        await client.call_tool("recall", arguments={"query": "nothing", "tier": "working"})
    item = result.content[0]
    assert isinstance(item, TextContent)
    returned = [ref["ref_id"] for ref in json.loads(item.text)]
    path = recall_log.log_path(settings)
    assert path is not None
    first, second = (json.loads(line) for line in path.read_text(encoding="utf-8").splitlines())
    assert first["origin"] == "tool" and first["session_id"] == "" and first["query"] == "database"
    assert first["ref_ids"] == returned and returned
    assert first["filters"] == {
        "type": "decision",
        "tier": None,
        "session_id_filter": None,
        "checkpoint_only": False,
        "top_k": 3,
        "include_needs_review": False,
        "order": "relevance",
    }
    assert second["query"] == "nothing" and second["filters"]["tier"] == "working" and second["ref_ids"] == []


def _text(result: object) -> str:
    item = result.content[0]  # type: ignore[attr-defined]
    assert isinstance(item, TextContent)
    return item.text


@pytest.mark.e2e
async def test_an_mcp_recall_record_is_a_receipt_with_the_callers_ids(tmp_path: Path) -> None:
    """memkernel-0-15-harness-foundations SC-3: run, agent and task ids (the call's winning over the process's),
    per-memory hashes and state, latency, size and exclusion counts; retain keeps the run; the response is a list."""
    settings = MemKernelSettings(
        project_id=f"e2e_{uuid.uuid4().hex[:8]}",
        chroma_persist_path=str(tmp_path / "chroma"),
        state_dir=str(tmp_path / "state"),
        recall_log=True,
        run_id="run-env",
        agent_id="agent-env",
    )
    async with Client(create_server(settings=settings, embedding=MockEmbedding(dimension=384))) as client:
        retained = await client.call_tool(
            "retain", arguments={"content": "We use PostgreSQL for users", "type": "decision", "run_id": "run-call"}
        )
        ref_id = json.loads(_text(retained))["ref_id"]
        got = json.loads(_text(await client.call_tool("get", arguments={"ref_id": ref_id})))
        result = await client.call_tool(
            "recall", arguments={"query": "database", "top_k": 3, "run_id": "run-call", "task_id": "task-7"}
        )
        long_id = "x" * (ID_MAX_CHARS + 1)
        refused_recall = await client.call_tool("recall", arguments={"query": "database", "agent_id": long_id})
        refused_retain = await client.call_tool(
            "retain", arguments={"content": "Another decision", "type": "decision", "task_id": long_id}
        )
    returned = json.loads(_text(result))
    assert isinstance(returned, list) and [ref["ref_id"] for ref in returned] == [ref_id]
    assert got["run_id"] == "run-call"
    path = recall_log.log_path(settings)
    assert path is not None
    (record,) = (json.loads(line) for line in path.read_text(encoding="utf-8").splitlines())
    assert (record["run_id"], record["agent_id"], record["task_id"]) == ("run-call", "agent-env", "task-7")
    (entry,) = record["memories"]
    assert entry["ref_id"] == ref_id and entry["content_hash"] == got["content_hash"]
    assert entry["content_hash_scheme"] == CONTENT_HASH_SCHEME and entry["state"] == "live"
    assert record["returned_chars"] == len(_text(result))  # the whole response, not only the previews
    assert record["latency_ms"] >= 0 and set(record["excluded"]) == set(EXCLUSION_REASONS)
    for refused in (refused_recall, refused_retain):
        assert refused.is_error and f"the limit is {ID_MAX_CHARS}" in _text(refused)

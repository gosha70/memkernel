# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""Scope over MCP (memkernel-0-15-harness-foundations H2: SC-1, SC-6, B1, B2, B7, B10, B11)."""

from __future__ import annotations

import json
import uuid
from typing import TYPE_CHECKING, Any

import pytest
from mcp import Client
from mcp.types import TextContent

from memkernel import recall_log
from memkernel.config import MemKernelSettings
from memkernel.mcp.server import create_server
from tests.conftest import MockEmbedding

if TYPE_CHECKING:
    from pathlib import Path


def _json(result: Any) -> Any:
    item = result.content[0]
    assert isinstance(item, TextContent)
    return json.loads(item.text)


@pytest.mark.e2e
async def test_one_agents_private_memory_is_invisible_to_another_over_every_tool(tmp_path: Path) -> None:
    settings = MemKernelSettings(
        project_id=f"e2e_{uuid.uuid4().hex[:8]}",
        chroma_persist_path=str(tmp_path / "chroma"),
        state_dir=str(tmp_path / "state"),
        recall_log=True,
    )
    a, b = {"agent_id": "a"}, {"agent_id": "b"}
    async with Client(create_server(settings=settings, embedding=MockEmbedding(dimension=384))) as client:
        shared = _json(await client.call_tool("retain", {"content": "Lambda builds use cache v2", "type": "fact"}))
        mine = _json(
            await client.call_tool(
                "retain", {"content": "Lambda builds flake for agent a", "type": "observation", "scope": "agent", **a}
            )
        )["ref_id"]
        refused = await client.call_tool("retain", {"content": "x", "type": "fact", "scope": "agent"})
        recall_a = _json(await client.call_tool("recall", {"query": "Lambda builds", "top_k": 5, **a}))
        recall_b = _json(await client.call_tool("recall", {"query": "Lambda builds", "top_k": 5, **b}))
        empty_b = _json(await client.call_tool("recall", {"query": "flake for agent a", "top_k": 5, **b}))
        get_b = _json(await client.call_tool("get", {"ref_id": mine, **b}))
        ask_b = _json(await client.call_tool("ask", {"ref_id": mine, "question": "what?", **b}))
        promote_b = _json(await client.call_tool("promote", {"ref_id": mine, "type": "fact", **b}))
        candidates_b = _json(await client.call_tool("consolidate", {**b}))["candidates"]
        forget_b = _json(await client.call_tool("forget", {"ref_id": mine, **b}))
        published = _json(await client.call_tool("promote", {"ref_id": mine, "type": "fact", "scope": "project", **a}))[
            "ref_id"
        ]
        get_published_b = _json(await client.call_tool("get", {"ref_id": published, **b}))

    assert refused.is_error and "needs the caller's agent_id" in refused.content[0].text  # type: ignore[union-attr]
    assert {r["ref_id"] for r in recall_a} == {shared["ref_id"], mine}
    assert {r["ref_id"] for r in recall_b} == {shared["ref_id"]}
    assert all(r["ref_id"] != mine for r in empty_b)
    assert get_b["error"] == "not_found" and ask_b["error"] == "not_found" and promote_b["error"] == "not_found"
    assert mine not in {c["ref_id"] for c in candidates_b} and forget_b["deleted"] is False
    assert get_published_b["scope"] == "project"

    path = recall_log.log_path(settings)
    assert path is not None
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    by_agent = {(r["agent_id"], r["query"]): r for r in records}
    entry = next(e for e in by_agent[("a", "Lambda builds")]["memories"] if e["ref_id"] == mine)
    assert entry["scope"] == "agent:a"  # B10: the receipt names a non-project scope
    assert all("scope" not in e for e in by_agent[("b", "Lambda builds")]["memories"])  # b received project only
    assert by_agent[("b", "Lambda builds")]["excluded"]["out_of_scope"] >= 1

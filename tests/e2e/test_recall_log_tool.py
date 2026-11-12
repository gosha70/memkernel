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
from memkernel.mcp.server import create_server
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

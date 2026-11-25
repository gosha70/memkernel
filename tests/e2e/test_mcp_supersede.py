# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""retain's MCP response carries supersede suggestions (memkernel-0-17-supersede-and-canonical-hash D1)."""

from __future__ import annotations

import json
import uuid
from typing import Any

import pytest
from mcp import Client
from mcp.types import TextContent

from memkernel.config import MemKernelSettings
from memkernel.mcp.server import create_server
from tests.conftest import MockEmbedding


def _json(result: Any) -> Any:
    item = result.content[0]
    assert isinstance(item, TextContent)
    return json.loads(item.text)


@pytest.mark.e2e
async def test_retain_returns_supersede_suggestions_beside_the_ref_id() -> None:
    settings = MemKernelSettings(
        project_id=f"e2e_{uuid.uuid4().hex[:8]}", chroma_persist_path="", supersede_suggest_threshold=0.0
    )
    async with Client(create_server(settings=settings, embedding=MockEmbedding(dimension=384))) as client:
        old = _json(await client.call_tool("retain", {"content": "Use PostgreSQL 15.", "type": "decision"}))
        new = _json(await client.call_tool("retain", {"content": "Use PostgreSQL 16.", "type": "decision"}))
        again = _json(await client.call_tool("retain", {"content": "Use PostgreSQL 16.", "type": "decision"}))
        task = _json(await client.call_tool("retain", {"content": "Upgrade the DB.", "type": "task"}))
    assert old["supersede_suggestions"] == []
    (suggestion,) = new["supersede_suggestions"]
    assert suggestion["ref_id"] == old["ref_id"] and set(suggestion) == {"ref_id", "similarity", "preview"}
    assert suggestion["preview"] == "Use PostgreSQL 15."
    assert again["ref_id"] == new["ref_id"] and again["supersede_suggestions"] == []  # a dedup hit: none
    assert task["supersede_suggestions"] == []  # working memory: none (D2)

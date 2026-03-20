"""E2E tests: MCP client round-trip via in-memory transport."""

from __future__ import annotations

import json

import pytest
from mcp.shared.memory import create_connected_server_and_client_session
from mcp.types import CallToolResult, TextContent

from memkernel.config import MemKernelSettings
from memkernel.mcp.server import create_server
from tests.conftest import MockEmbedding


def _text(result: CallToolResult) -> str:
    """Extract text from the first content block of a tool result."""
    item = result.content[0]
    assert isinstance(item, TextContent)
    return item.text


def _test_settings() -> MemKernelSettings:
    """Settings for E2E tests — ephemeral ChromaDB, unique project."""
    import uuid

    return MemKernelSettings(
        project_id=f"e2e_{uuid.uuid4().hex[:8]}",
        chroma_persist_path="",  # empty string triggers EphemeralClient in ChromaVectorStore
    )


@pytest.mark.e2e
async def test_stdio_roundtrip_retain_recall_get_forget() -> None:
    """Full MCP round-trip: retain → recall → get → forget → recall (empty)."""
    settings = _test_settings()
    mock_emb = MockEmbedding(dimension=384)
    server = create_server(settings=settings, embedding=mock_emb)

    async with create_connected_server_and_client_session(server) as client:
        # 1. Retain a decision
        result = await client.call_tool(
            "retain",
            arguments={
                "content": "We decided to use PostgreSQL for the user database",
                "type": "decision",
                "session_id": "session-1",
            },
        )
        retain_response = json.loads(_text(result))
        ref_id = retain_response["ref_id"]
        assert ref_id

        # 2. Recall by query
        result = await client.call_tool(
            "recall",
            arguments={"query": "database decision", "top_k": 5},
        )
        recall_response = json.loads(_text(result))
        assert len(recall_response) >= 1
        first = recall_response[0]
        assert first["ref_id"] == ref_id
        assert "preview" in first
        assert "score" in first
        assert "token_count" in first
        assert "type" in first
        assert "timestamp" in first
        # ArtifactRef must NOT contain checkpoint (FR-003)
        assert "checkpoint" not in first

        # 3. Get full content
        result = await client.call_tool("get", arguments={"ref_id": ref_id})
        get_response = json.loads(_text(result))
        assert get_response["content"] == "We decided to use PostgreSQL for the user database"
        assert get_response["type"] == "decision"
        assert get_response["session_id"] == "session-1"

        # 4. Forget
        result = await client.call_tool("forget", arguments={"ref_id": ref_id})
        forget_response = json.loads(_text(result))
        assert forget_response["deleted"] is True

        # 5. Recall should return empty
        result = await client.call_tool(
            "recall",
            arguments={"query": "database decision", "top_k": 5},
        )
        recall_after = json.loads(_text(result))
        assert len(recall_after) == 0


@pytest.mark.e2e
async def test_dedup_same_content_same_type_returns_same_ref_id() -> None:
    """Retaining identical content+type returns the same ref_id (ADR-5)."""
    settings = _test_settings()
    mock_emb = MockEmbedding(dimension=384)
    server = create_server(settings=settings, embedding=mock_emb)

    async with create_connected_server_and_client_session(server) as client:
        content = "Always use snake_case for Python function names"

        r1 = await client.call_tool(
            "retain",
            arguments={"content": content, "type": "convention", "session_id": "s1"},
        )
        ref_id_1 = json.loads(_text(r1))["ref_id"]

        r2 = await client.call_tool(
            "retain",
            arguments={"content": content, "type": "convention", "session_id": "s2"},
        )
        ref_id_2 = json.loads(_text(r2))["ref_id"]

        assert ref_id_1 == ref_id_2

        # session_id should be updated to s2
        result = await client.call_tool("get", arguments={"ref_id": ref_id_1})
        memory = json.loads(_text(result))
        assert memory["session_id"] == "s2"


@pytest.mark.e2e
async def test_dedup_same_content_different_type_creates_new_memory() -> None:
    """Same content with different type creates a separate memory (ADR-5 widened key)."""
    settings = _test_settings()
    mock_emb = MockEmbedding(dimension=384)
    server = create_server(settings=settings, embedding=mock_emb)

    async with create_connected_server_and_client_session(server) as client:
        content = "The auth service uses JWT tokens"

        r1 = await client.call_tool(
            "retain",
            arguments={"content": content, "type": "decision"},
        )
        ref_id_1 = json.loads(_text(r1))["ref_id"]

        r2 = await client.call_tool(
            "retain",
            arguments={"content": content, "type": "episode"},
        )
        ref_id_2 = json.loads(_text(r2))["ref_id"]

        assert ref_id_1 != ref_id_2


@pytest.mark.e2e
async def test_recall_with_type_filter() -> None:
    """Recall with type filter returns only matching type."""
    settings = _test_settings()
    mock_emb = MockEmbedding(dimension=384)
    server = create_server(settings=settings, embedding=mock_emb)

    async with create_connected_server_and_client_session(server) as client:
        await client.call_tool(
            "retain",
            arguments={"content": "Use React for frontend", "type": "decision"},
        )
        await client.call_tool(
            "retain",
            arguments={"content": "Sprint planning every Monday", "type": "episode"},
        )

        result = await client.call_tool(
            "recall",
            arguments={"query": "React frontend planning", "type": "decision"},
        )
        refs = json.loads(_text(result))
        assert all(r["type"] == "decision" for r in refs)


@pytest.mark.e2e
async def test_get_not_found() -> None:
    """Get with non-existent ref_id returns error."""
    settings = _test_settings()
    mock_emb = MockEmbedding(dimension=384)
    server = create_server(settings=settings, embedding=mock_emb)

    async with create_connected_server_and_client_session(server) as client:
        result = await client.call_tool("get", arguments={"ref_id": "nonexistent-id"})
        response = json.loads(_text(result))
        assert response["error"] == "not_found"


@pytest.mark.e2e
async def test_tool_count_under_10() -> None:
    """FR-013: Total MCP tool count must be under 10."""
    settings = _test_settings()
    mock_emb = MockEmbedding(dimension=384)
    server = create_server(settings=settings, embedding=mock_emb)

    async with create_connected_server_and_client_session(server) as client:
        tools = await client.list_tools()
        tool_names = [t.name for t in tools.tools]
        assert len(tool_names) < 10
        assert set(tool_names) == {"retain", "recall", "get", "forget"}

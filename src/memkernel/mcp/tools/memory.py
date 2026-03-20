# Copyright (c) EGOGE - All Rights Reserved.
# This software may be used and distributed according to the terms of the MIT license.
"""MCP tool registrations: retain, recall, get, forget."""

from __future__ import annotations

import json
from typing import Any

from mcp.server.fastmcp import FastMCP  # noqa: TC002 — runtime import required by FastMCP introspection
from mcp.server.fastmcp.server import Context  # noqa: TC002

from memkernel.core.models import MemoryType


def register_memory_tools(server: FastMCP[Any]) -> None:
    """Register retain, recall, get, forget tools on the server."""

    @server.tool()
    async def retain(
        content: str,
        type: str,  # noqa: A002
        session_id: str | None = None,
        checkpoint: bool = False,
        source: str = "",
        ctx: Context[Any, Any, Any] | None = None,
    ) -> str:
        """Store a memory. Returns ref_id. Idempotent for identical content+type."""
        if ctx is None:
            raise RuntimeError("Tool called outside of MCP request context")
        svc = ctx.request_context.lifespan_context.memory_service
        memory_type = MemoryType(type)
        ref_id = svc.retain(
            content=content,
            type=memory_type,
            session_id=session_id,
            checkpoint=checkpoint,
            source=source,
        )
        return json.dumps({"ref_id": ref_id})

    @server.tool()
    async def recall(
        query: str,
        type: str | None = None,  # noqa: A002
        session_id: str | None = None,
        checkpoint_only: bool = False,
        top_k: int | None = None,
        ctx: Context[Any, Any, Any] | None = None,
    ) -> str:
        """Search memories by query. Returns ref_id + preview pairs. Use get(ref_id) for full content."""
        if ctx is None:
            raise RuntimeError("Tool called outside of MCP request context")
        svc = ctx.request_context.lifespan_context.memory_service
        type_filter = MemoryType(type) if type else None
        results = svc.recall(
            query=query,
            type=type_filter,
            session_id=session_id,
            checkpoint_only=checkpoint_only,
            top_k=top_k,
        )
        return json.dumps([ref.model_dump(mode="json") for ref in results])

    @server.tool()
    async def get(
        ref_id: str,
        ctx: Context[Any, Any, Any] | None = None,
    ) -> str:
        """Retrieve full content of a memory by ref_id."""
        if ctx is None:
            raise RuntimeError("Tool called outside of MCP request context")
        svc = ctx.request_context.lifespan_context.memory_service
        memory = svc.get(ref_id)
        if memory is None:
            return json.dumps({"error": "not_found", "ref_id": ref_id})
        return json.dumps(memory.model_dump(mode="json", exclude={"chunk_refs"}))

    @server.tool()
    async def forget(
        ref_id: str,
        ctx: Context[Any, Any, Any] | None = None,
    ) -> str:
        """Delete a memory by ref_id. Removes from all indexes."""
        if ctx is None:
            raise RuntimeError("Tool called outside of MCP request context")
        svc = ctx.request_context.lifespan_context.memory_service
        deleted = svc.forget(ref_id)
        return json.dumps({"ref_id": ref_id, "deleted": deleted})

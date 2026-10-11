# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""MCP tool registrations: retain, recall, get, forget, promote, consolidate, forget_expired."""

from __future__ import annotations

import json
from typing import Any

from mcp.server.fastmcp import FastMCP  # noqa: TC002 — runtime import required by FastMCP introspection
from mcp.server.fastmcp.server import Context  # noqa: TC002

from memkernel.core.models import MemoryTier, MemoryType


def _service(ctx: Context[Any, Any, Any] | None) -> Any:
    if ctx is None:
        raise RuntimeError("Tool called outside of MCP request context")
    return ctx.request_context.lifespan_context.memory_service


def register_memory_tools(server: FastMCP[Any]) -> None:
    """Register the memory tools on the server."""

    @server.tool()
    async def retain(
        content: str,
        type: str,  # noqa: A002
        session_id: str | None = None,
        checkpoint: bool = False,
        source: str = "",
        importance: float | None = None,
        tags: list[str] | None = None,
        supersedes: str | None = None,
        ctx: Context[Any, Any, Any] | None = None,
    ) -> str:
        """Store a memory. Returns ref_id. Idempotent for identical content+type.

        type: decision | convention | fact | code | procedure (long-term),
              episode | observation (short-term), task (working memory).
        importance: 0..1, defaults per type. supersedes: ref_id this memory replaces.
        """
        svc = _service(ctx)
        ref_id = svc.retain(
            content=content,
            type=MemoryType(type),
            session_id=session_id,
            checkpoint=checkpoint,
            source=source,
            importance=importance,
            tags=tags,
            supersedes=supersedes,
        )
        return json.dumps({"ref_id": ref_id})

    @server.tool()
    async def recall(
        query: str,
        type: str | None = None,  # noqa: A002
        tier: str | None = None,
        session_id: str | None = None,
        checkpoint_only: bool = False,
        top_k: int | None = None,
        ctx: Context[Any, Any, Any] | None = None,
    ) -> str:
        """Search memories by query. Returns ref_id + preview pairs ranked by relevance,
        recency and importance. Use get(ref_id) for full content.

        tier: working | short_term | long_term to restrict the search to one tier.
        """
        svc = _service(ctx)
        results = svc.recall(
            query=query,
            type=MemoryType(type) if type else None,
            tier=MemoryTier(tier) if tier else None,
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
        svc = _service(ctx)
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
        svc = _service(ctx)
        deleted = svc.forget(ref_id)
        return json.dumps({"ref_id": ref_id, "deleted": deleted})

    @server.tool()
    async def promote(
        ref_id: str,
        type: str,  # noqa: A002
        content: str | None = None,
        importance: float | None = None,
        tags: list[str] | None = None,
        ctx: Context[Any, Any, Any] | None = None,
    ) -> str:
        """Promote a short-term/working memory into a long-term type (decision, convention,
        fact, code, procedure). Pass the distilled `content`; defaults to the original text.
        Returns the new ref_id; the source memory is kept and linked via promoted_from.
        """
        svc = _service(ctx)
        new_ref = svc.promote(
            ref_id=ref_id,
            type=MemoryType(type),
            content=content,
            importance=importance,
            tags=tags,
        )
        if new_ref is None:
            return json.dumps({"error": "not_found", "ref_id": ref_id})
        return json.dumps({"ref_id": new_ref, "promoted_from": ref_id})

    @server.tool()
    async def consolidate(
        session_id: str | None = None,
        limit: int = 20,
        ctx: Context[Any, Any, Any] | None = None,
    ) -> str:
        """Run a consolidation pass: purge expired short-term memories and return the
        short-term/working memories most worth promoting (ranked by importance and how
        often they were recalled). Call promote(ref_id, type, content) for the keepers.
        """
        svc = _service(ctx)
        return json.dumps(svc.consolidate(session_id=session_id, limit=limit))

    @server.tool()
    async def forget_expired(
        ctx: Context[Any, Any, Any] | None = None,
    ) -> str:
        """Delete every short-term/working memory whose retention window has lapsed."""
        svc = _service(ctx)
        return json.dumps({"deleted": svc.forget_expired()})

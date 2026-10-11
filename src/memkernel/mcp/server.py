# Copyright (c) EGOGE - All Rights Reserved.
# This software may be used and distributed according to the terms of the MIT license.
"""MCP server factory and entry point."""

from __future__ import annotations

import json
import logging
import sys
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.server import Context  # noqa: TC002 — runtime import for introspection

from memkernel.config import MemKernelSettings
from memkernel.factory import build_service
from memkernel.mcp.tools.memory import register_memory_tools
from memkernel.mcp.tools.wiki import register_wiki_tools

if TYPE_CHECKING:
    from memkernel.core.ports import EmbeddingPort
    from memkernel.core.services import MemoryService

logger = logging.getLogger(__name__)


@dataclass
class MemKernelContext:
    """Lifespan context shared with all tool handlers."""

    memory_service: MemoryService
    settings: MemKernelSettings


def create_server(
    settings: MemKernelSettings | None = None,
    embedding: EmbeddingPort | None = None,
) -> FastMCP[MemKernelContext]:
    """Factory — single source of truth for settings.

    The lifespan closure captures ``settings`` from here.
    Tests pass custom settings (e.g. in-memory chroma) and a MockEmbedding;
    production calls with None to load from env and use the real model.
    """
    resolved_settings = settings or MemKernelSettings()
    captured_embedding = embedding

    @asynccontextmanager
    async def lifespan(server: FastMCP[MemKernelContext]) -> AsyncIterator[MemKernelContext]:
        memory_service = build_service(settings=resolved_settings, embedding=captured_embedding)
        yield MemKernelContext(memory_service=memory_service, settings=resolved_settings)

    server: FastMCP[MemKernelContext] = FastMCP(
        "MemKernel",
        host=resolved_settings.host,
        port=resolved_settings.port,
        lifespan=lifespan,
    )
    register_memory_tools(server)
    register_wiki_tools(server)
    _register_health_resource(server)
    return server


def _register_health_resource(server: FastMCP[MemKernelContext]) -> None:
    @server.resource("memory://status")
    async def status(ctx: Context[Any, MemKernelContext]) -> str:
        """Server health and memory statistics."""
        app_ctx: MemKernelContext = ctx.request_context.lifespan_context
        count = app_ctx.memory_service.count()
        return json.dumps(
            {
                "status": "ok",
                "project_id": app_ctx.settings.project_id,
                "memory_count": count,
            }
        )


def main() -> None:
    """CLI entry point."""
    logging.basicConfig(stream=sys.stderr, level=logging.INFO)
    settings = MemKernelSettings()
    server = create_server(settings)
    server.run(transport=settings.transport)


if __name__ == "__main__":
    main()

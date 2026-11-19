# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""MCP server factory and entry point."""

from __future__ import annotations

import json
import logging
import sys
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings

from memkernel.config import MemKernelSettings
from memkernel.factory import build_service
from memkernel.mcp.tools.memory import register_memory_tools
from memkernel.mcp.tools.wiki import register_wiki_tools

if TYPE_CHECKING:
    from memkernel.core.ports import EmbeddingPort
    from memkernel.core.services import MemoryService

logger = logging.getLogger(__name__)

# The HTTP transport's Host/Origin check (#148): which binds are loopback, and which listen on every interface.
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
WILDCARD_HOSTS = frozenset({"0.0.0.0", "::", ""})  # noqa: S104 (names, not a bind)
_LOOPBACK_NAMES = ("127.0.0.1", "localhost", "::1")  # what the SDK itself allows on a loopback bind


@dataclass
class MemKernelContext:
    """Lifespan context shared with all tool handlers."""

    memory_service: MemoryService
    settings: MemKernelSettings


@dataclass
class _Running:
    """The lifespan context while the server runs, for handlers that cannot take a Context (static resources)."""

    context: MemKernelContext | None = None


def create_server(
    settings: MemKernelSettings | None = None,
    embedding: EmbeddingPort | None = None,
) -> MCPServer[MemKernelContext]:
    """Factory — single source of truth for settings.

    The lifespan closure captures ``settings`` from here.
    Tests pass custom settings (e.g. in-memory chroma) and a MockEmbedding;
    production calls with None to load from env and use the real model.
    """
    resolved_settings = settings or MemKernelSettings()
    captured_embedding = embedding
    running = _Running()

    @asynccontextmanager
    async def lifespan(server: MCPServer[MemKernelContext]) -> AsyncIterator[MemKernelContext]:
        memory_service = build_service(settings=resolved_settings, embedding=captured_embedding)
        running.context = MemKernelContext(memory_service=memory_service, settings=resolved_settings)
        try:
            yield running.context
        finally:
            running.context = None

    server: MCPServer[MemKernelContext] = MCPServer("MemKernel", lifespan=lifespan)
    register_memory_tools(server)
    register_wiki_tools(server)
    _register_health_resource(server, running)
    return server


def run_server(server: MCPServer[MemKernelContext], settings: MemKernelSettings) -> None:
    """Serve on the configured transport; host and port apply to Streamable HTTP only."""
    if settings.transport == "streamable-http":
        security = transport_security(settings)
        server.run("streamable-http", host=settings.host, port=settings.port, transport_security=security)
    else:
        server.run("stdio")


def transport_security(settings: MemKernelSettings) -> TransportSecuritySettings | None:
    """The HTTP transport's Host/Origin check (#148), following ``MEMKERNEL_HOST``; there is no authentication.

    The SDK already turns the check on for a loopback bind, with these loopback names; this keeps that and adds
    ``MEMKERNEL_ALLOWED_HOSTS``. A non-loopback bind had no check: a specific address now allows itself, with a
    warning; a wildcard bind allows only ``MEMKERNEL_ALLOWED_HOSTS``, and without them runs unchecked, as before,
    with a warning. ``MEMKERNEL_ALLOWED_HOSTS`` adds names in every case. A request with another ``Host`` gets 421,
    one with another ``Origin`` 403; a request without an ``Origin`` (any non-browser client) is not refused for it.
    """
    host = settings.host.strip()
    extra = [name.strip() for name in settings.allowed_hosts.split(",") if name.strip()]
    if host in LOOPBACK_HOSTS:
        names = [*_LOOPBACK_NAMES, *extra]
    elif host in WILDCARD_HOSTS:
        if not extra:
            logger.warning(
                "memkernel: MEMKERNEL_HOST=%s listens on every interface with no Host/Origin check and no "
                "authentication; set MEMKERNEL_ALLOWED_HOSTS to the names clients use, or bind 127.0.0.1",
                host or "(empty)",
            )
            return None
        names = extra
    else:
        names = [host, *extra]
    if host not in LOOPBACK_HOSTS:
        logger.warning("memkernel: MEMKERNEL_HOST=%s is not a loopback address and there is no authentication", host)
    hosts = [form for name in names for form in (_host_form(name), f"{_host_form(name)}:*")]
    origins = [f"{scheme}://{_host_form(name)}:*" for name in names for scheme in ("http", "https")]
    return TransportSecuritySettings(enable_dns_rebinding_protection=True, allowed_hosts=hosts, allowed_origins=origins)


def _host_form(name: str) -> str:
    """A host as it appears in a ``Host`` header: an IPv6 address (two or more colons) in brackets."""
    return f"[{name}]" if name.count(":") >= 2 and not name.startswith("[") else name


def _register_health_resource(server: MCPServer[MemKernelContext], running: _Running) -> None:
    # mcp 2.x takes no Context on a static resource and has no get_context(),
    # so the handler reads the lifespan context through `running`.
    @server.resource("memory://status")
    async def status() -> str:
        """Server health, memory count and the quick store-health summary."""
        app_ctx = running.context
        if app_ctx is None:
            raise RuntimeError("memory://status is readable only while the server runs")
        count = app_ctx.memory_service.count()
        return json.dumps(
            {
                "status": "ok",
                "project_id": app_ctx.settings.project_id,
                "memory_count": count,
                "health": app_ctx.memory_service.health(full=False).summary,
            }
        )


_USAGE = """usage: memkernel [--version] [--help]

MemKernel MCP server. With no arguments it starts the server on the configured
transport (MEMKERNEL_TRANSPORT=stdio|streamable-http) and waits for a client;
stop it with Ctrl-C. All settings come from MEMKERNEL_* environment variables
(see the README configuration table).

  -V, --version  print the version and exit
  -h, --help     print this help and exit
"""


def main(argv: list[str] | None = None) -> int:
    """CLI entry point.

    ``--version`` / ``--help`` print and exit; other arguments are an error;
    no arguments starts the server.
    """
    args = sys.argv[1:] if argv is None else argv
    if args in (["--version"], ["-V"]):
        from memkernel import __version__

        print(f"memkernel {__version__}")
        return 0
    if args in (["--help"], ["-h"]):
        print(_USAGE, end="")
        return 0
    if args:
        print(f"memkernel: unknown arguments: {' '.join(args)}\n{_USAGE}", end="", file=sys.stderr)
        return 2
    logging.basicConfig(stream=sys.stderr, level=logging.INFO)
    settings = MemKernelSettings()
    run_server(create_server(settings), settings)
    return 0


if __name__ == "__main__":
    sys.exit(main())

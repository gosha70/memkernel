# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""MCP tool registrations for the LLM-wiki bridge: wiki_export, wiki_import."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP  # noqa: TC002 — runtime import required by FastMCP introspection
from mcp.server.fastmcp.server import Context  # noqa: TC002

from memkernel.wiki.sync import WikiExporter, WikiImporter


def _context(ctx: Context[Any, Any, Any] | None) -> Any:
    if ctx is None:
        raise RuntimeError("Tool called outside of MCP request context")
    return ctx.request_context.lifespan_context


def _resolve_wiki_dir(wiki_dir: str | None, settings: Any) -> Path:
    resolved = wiki_dir or settings.wiki_dir
    if not resolved:
        raise ValueError("No wiki directory: pass wiki_dir or set MEMKERNEL_WIKI_DIR")
    return Path(resolved)


def register_wiki_tools(server: FastMCP[Any]) -> None:
    """Register wiki_export and wiki_import on the server."""

    @server.tool()
    async def wiki_export(
        wiki_dir: str | None = None,
        ctx: Context[Any, Any, Any] | None = None,
    ) -> str:
        """Compile long-term memories (decision, convention, fact, procedure) that have no wiki
        page yet into draft markdown pages under wiki_dir (default MEMKERNEL_WIKI_DIR), and
        append them to index.md and log.md. Review and curate the drafts before marking stable.
        """
        app_ctx = _context(ctx)
        exporter = WikiExporter(app_ctx.memory_service, _resolve_wiki_dir(wiki_dir, app_ctx.settings))
        report = exporter.export()
        return json.dumps({"written": report.written, "skipped": report.skipped})

    @server.tool()
    async def wiki_import(
        wiki_dir: str | None = None,
        ctx: Context[Any, Any, Any] | None = None,
    ) -> str:
        """Index every curated wiki page under wiki_dir (default MEMKERNEL_WIKI_DIR) as a
        long-term memory so recall() can find it. Idempotent: unchanged pages dedup, changed
        pages supersede their previous version.
        """
        app_ctx = _context(ctx)
        importer = WikiImporter(app_ctx.memory_service, _resolve_wiki_dir(wiki_dir, app_ctx.settings))
        report = importer.import_pages()
        return json.dumps({"imported": report.imported, "skipped": report.skipped})

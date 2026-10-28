# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""MCP tool registrations for the LLM-wiki bridge: wiki_export, wiki_import."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP  # noqa: TC002 — runtime import required by FastMCP introspection
from mcp.server.fastmcp.server import Context  # noqa: TC002

from memkernel.wiki.studio import INSTALL_HINT
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
        With the memkernel[wiki] extra installed, "lint" carries wiki-studio's violations, audit
        errors and health findings for the whole wiki after the export (curated pages included);
        without the extra it is null and "lint_hint" says how to enable it; if the lint pass itself
        failed it is null and "lint_error" says why. With wiki-studio >= 0.7.0 the pages go through its
        promote gate (a missing index.md and log.md are created first by wiki-studio's init), and the
        response adds "proposal", "submission_digest" and "archived_dir" from wiki-studio's receipt.
        If "archived_dir" is null the pages landed but wiki-studio did not finish (no archive, or a
        failure after its commit, checked against its receipt), and "archive_hint" gives the command
        that finishes it; "receipt_error" says the receipt could not
        be read. A rejected export, or an installed wiki-studio that is broken or older than 0.7.0,
        writes no page and reports "gate_error" (a new wiki keeps the index.md and log.md init created).
        """
        app_ctx = _context(ctx)
        proposals = app_ctx.settings.wiki_proposals_dir
        exporter = WikiExporter(
            app_ctx.memory_service,
            _resolve_wiki_dir(wiki_dir, app_ctx.settings),
            project_root=Path(app_ctx.settings.project_root),
            proposals_dir=Path(proposals) if proposals else None,
        )
        report = exporter.export()
        payload: dict[str, Any] = {"written": report.written, "skipped": report.skipped}
        if report.gate_error is not None:
            payload["gate_error"] = report.gate_error
        if report.gated:
            payload["proposal"] = report.proposal
            payload["submission_digest"] = report.submission_digest
            payload["archived_dir"] = report.archived_dir
            if report.archive_hint is not None:
                payload["archive_hint"] = report.archive_hint
            if report.receipt_error is not None:
                payload["receipt_error"] = report.receipt_error
        if report.lint is not None:
            payload["lint"] = report.lint.model_dump(mode="json")
        elif report.lint_error is not None:
            payload["lint"] = None
            payload["lint_error"] = report.lint_error
        else:
            payload["lint"] = None
            payload["lint_hint"] = INSTALL_HINT
        return json.dumps(payload)

    @server.tool()
    async def wiki_import(
        wiki_dir: str | None = None,
        ctx: Context[Any, Any, Any] | None = None,
    ) -> str:
        """Index wiki pages under wiki_dir (default MEMKERNEL_WIKI_DIR) as long-term memories so
        recall() can find them. With wiki-studio >= 0.7.0 installed the import is governed
        ("governed": true): only pages wiki-studio reports approved, whose bytes are the approved
        revision, are imported; "not_approved" lists the others with their state and reason, and a
        page edited after approval keeps its last approved memory. An approved page's "corrects"
        frontmatter key (comma-separated memory ref_ids) supersedes the memories it names, keeping
        their records: "corrections" lists them, "unresolved" the references not applied (unknown,
        another project's, a wiki memory, already superseded) with a reason, "invalid_corrects" a
        value that breaks the grammar. Without wiki-studio every page file is imported, drafts
        included ("governed": false). An installed wiki-studio that is broken or older than 0.7.0
        imports nothing and reports "import_error". "skipped" lists pages that cannot be imported
        (unmapped type, deprecated, unparsable); "unchanged" lists approved pages already current,
        whose corrects are still reconciled. Idempotent: a changed page supersedes its previous
        version.
        """
        app_ctx = _context(ctx)
        importer = WikiImporter(
            app_ctx.memory_service,
            _resolve_wiki_dir(wiki_dir, app_ctx.settings),
            project_root=Path(app_ctx.settings.project_root),
        )
        report = importer.import_pages()
        payload: dict[str, Any] = {"imported": report.imported, "skipped": report.skipped, "governed": report.governed}
        if report.import_error is not None:
            payload["import_error"] = report.import_error
        for key in ("unchanged", "not_approved", "corrections", "unresolved", "invalid_corrects"):
            value = getattr(report, key)
            if value:
                payload[key] = value
        return json.dumps(payload)

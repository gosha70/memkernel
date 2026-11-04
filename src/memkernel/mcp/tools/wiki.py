# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""MCP tool registrations for the LLM-wiki bridge: wiki_export, wiki_import."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP  # noqa: TC002 — runtime import required by FastMCP introspection
from mcp.server.fastmcp.server import Context  # noqa: TC002

from memkernel.wiki.studio import INSTALL_HINT, WIKI_MODE_UNGATED
from memkernel.wiki.sync import UNGATED_LINT_HINT, WikiExporter, WikiImporter


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
        that tries to finish it (wiki-studio may refuse it, writing nothing, if the wiki or the proposal
        changed since);
        "receipt_error" says the receipt could not be read or used. A rejected export, or an installed
        wiki-studio that is broken or older than 0.7.0, writes no page and reports "gate_error" (a new
        wiki keeps the index.md and log.md init created). If wiki-studio failed during its commit and
        its receipt shows neither a commit nor a rollback, "gate_error" comes with "uncertain_outcome"
        and "proposal": the pages may be on disk; compare the wiki with the named receipt.json.
        At most MEMKERNEL_WIKI_EXPORT_BATCH new pages are written per call (default 10, most important
        first); "remaining" counts the eligible memories still without a page (null when the outcome is
        uncertain, or when governed refused before reading the wiki). Each page carries memkernel_sha256
        and, for a clean tracked source file, the commit it is grounded at. "mode" is the path that ran
        (gated or ungated) and "configured_mode" the MEMKERNEL_WIKI_MODE setting: governed refuses,
        writing nothing, unless wiki-studio and a governed wiki pass its checks; ungated never loads
        wiki-studio.
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
        payload: dict[str, Any] = {
            "written": report.written,
            "skipped": report.skipped,
            "remaining": report.remaining,
            "mode": report.mode,
            "configured_mode": report.configured_mode,
        }
        if report.gate_error is not None:
            payload["gate_error"] = report.gate_error
        if report.uncertain_outcome is not None:
            payload["uncertain_outcome"] = report.uncertain_outcome
            payload["proposal"] = report.proposal
            if report.receipt_error is not None:
                payload["receipt_error"] = report.receipt_error
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
            payload["lint_hint"] = UNGATED_LINT_HINT if report.configured_mode == WIKI_MODE_UNGATED else INSTALL_HINT
        return json.dumps(payload)

    @server.tool()
    async def wiki_import(
        wiki_dir: str | None = None,
        adopt_legacy: bool = False,
        adopt_pages: list[dict[str, str]] | None = None,
        adopt_manifest: bool = False,
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
        (unmapped type, unparsable, or deprecated with nothing to withdraw); "unchanged" lists approved
        pages already current, whose corrects are still reconciled. Idempotent: a changed page
        supersedes its previous version. A governed import also takes memories out of the current
        answers, keeping their records: "withdrawn" lists memories of deleted pages (only those this
        wiki's sync ledger recorded) and of deprecated pages once that revision is approved;
        "superseded" lists memories of superseded pages replaced by their successor page's memory;
        "pending" lists actions waiting (a successor with no memory yet); "sync_failed" lists failed
        actions, retried at the next import; "ledger_error" says the sync ledger was unreadable and
        was rebuilt. Every imported memory carries its wiki's identity (wiki-path, and wiki-id with a
        manifest); a page's previous memory is only this wiki's. "ambiguous" lists pages left untouched
        ({"path", "ref_ids", "reason"}): a memory from before 0.7 is adopted only on the owner's word,
        adopt_legacy=true (each page's sole such memory) or adopt_pages=[{"path", "ref_id"}, ...]
        (exactly those, copied from "ambiguous"); adopt_manifest=true says a wiki that gained a manifest
        is the same wiki. "mode" is the path that ran (gated or ungated) and "configured_mode" the
        MEMKERNEL_WIKI_MODE setting: governed refuses, importing nothing, unless wiki-studio and a
        governed wiki pass its checks; ungated never loads wiki-studio and reads the files.
        """
        app_ctx = _context(ctx)
        importer = WikiImporter(
            app_ctx.memory_service,
            _resolve_wiki_dir(wiki_dir, app_ctx.settings),
            project_root=Path(app_ctx.settings.project_root),
        )
        report = importer.import_pages(
            adopt_legacy=adopt_legacy, adopt_pages=adopt_pages, adopt_manifest=adopt_manifest
        )
        payload: dict[str, Any] = {
            "imported": report.imported,
            "skipped": report.skipped,
            "governed": report.governed,
            "mode": report.mode,
            "configured_mode": report.configured_mode,
        }
        if report.import_error is not None:
            payload["import_error"] = report.import_error
        if report.ledger_error is not None:
            payload["ledger_error"] = report.ledger_error
        for key in (
            "unchanged",
            "not_approved",
            "corrections",
            "unresolved",
            "invalid_corrects",
            "withdrawn",
            "superseded",
            "pending",
            "sync_failed",
            "ambiguous",
        ):
            value = getattr(report, key)
            if value:
                payload[key] = value
        return json.dumps(payload)

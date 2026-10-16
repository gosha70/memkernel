# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""Optional wiki-studio integration (the ``memkernel[wiki]`` extra, ADR-010).

wiki-studio owns the wiki page schema and its lint and health pass. This
module is the only place memkernel imports it, lazily: without the extra
every function here returns ``None`` and logs nothing, because a missing
optional extra is a normal state. A warning is logged only when the caller
asked for wiki-studio explicitly (``require_studio=True``). Nothing here ever calls
wiki-studio's ``ingest``, ``query`` or a copilot-CLI backend: those shell out
to a copilot CLI, and memkernel runs inside one.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

INSTALL_HINT = "install memkernel[wiki] for lint and health"


class HealthItem(BaseModel):
    """One knowledge-health finding, field for field as wiki-studio's ``HealthFinding``."""

    kind: str
    severity: str
    pages: list[str]
    description: str


class LintSummary(BaseModel):
    """wiki-studio's structural lint, audit-format and health results for one wiki directory."""

    violations: list[str] = Field(default_factory=list)
    audit_errors: list[str] = Field(default_factory=list)
    pages_checked: int = 0
    health: list[HealthItem] | None = None


class LintError(RuntimeError):
    """wiki-studio is installed but its lint pass failed; the export itself is unaffected."""


def load_studio(*, require_studio: bool = False) -> Any | None:
    """Return the ``wiki_studio.api`` module, or ``None`` when the extra is not installed."""
    try:
        import wiki_studio.api as api
    except ImportError:
        if require_studio:
            logger.warning("wiki-studio is not installed; %s", INSTALL_HINT)
        return None
    return api


def lint_wiki(wiki_dir: Path, project_root: Path, *, require_studio: bool = False) -> LintSummary | None:
    """Run wiki-studio's lint with the health checks over the whole wiki in ``wiki_dir``.

    Returns ``None`` without the extra. Raises :class:`LintError` when wiki-studio
    is installed but the pass fails (a page that is not valid UTF-8, a malformed
    audit tree, a bug in wiki-studio): the caller decides what the failure means
    for its own result. ``project_root`` is the root ``path:`` sources resolve
    against (memkernel's ``MEMKERNEL_PROJECT_ROOT``). No backend is passed, so
    the LLM-dependent contradiction check is skipped.
    """
    api = load_studio(require_studio=require_studio)
    if api is None:
        return None
    from wiki_studio.paths import WikiPaths

    try:
        result = api.lint(WikiPaths.for_root(project_root, wiki_dir=wiki_dir), health=True)
    except Exception as exc:  # third-party failure: wrapped, never silent (the extra is installed)
        logger.warning("wiki-studio lint failed for %s: %s", wiki_dir, exc)
        raise LintError(f"wiki-studio lint failed: {exc}") from exc
    health = (
        [
            HealthItem(
                kind=str(finding.kind),
                severity=str(finding.severity),
                pages=list(finding.pages),
                description=finding.description,
            )
            for finding in result.health.findings
        ]
        if result.health is not None
        else None
    )
    return LintSummary(
        violations=list(result.violations),
        audit_errors=list(result.audit_errors),
        pages_checked=result.pages_checked,
        health=health,
    )

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

import json
import logging
import shlex
import sys
from dataclasses import dataclass
from importlib import metadata
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

INSTALL_HINT = "install memkernel[wiki] for lint and health"
GATE_BACKEND = "memkernel"
GATE_RATIONALE = "memkernel export"
# The gate's floor (ADR-010 addendum): 0.6.0 scopes the commit to the planned writes, rolls back on any
# exception including a write that failed part-way, and records a receipt, so memkernel keeps no snapshot.
GATE_MIN_VERSION = (0, 6, 0)
STUDIO_DISTRIBUTION = "wiki-studio"
RECEIPT_FILE = "receipt.json"


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
    """Return the ``wiki_studio.api`` module, or ``None`` when the extra is not installed.

    Only a missing ``wiki_studio`` package counts as absence. Any other import
    failure means the package is present but broken or incompatible, which is
    raised as :class:`LintError` so it is reported rather than mistaken for the
    extra being absent.
    """
    try:
        import wiki_studio.api as api
    except ModuleNotFoundError as exc:
        if exc.name == "wiki_studio":
            if require_studio:
                logger.warning("wiki-studio is not installed; %s", INSTALL_HINT)
            return None
        raise LintError(f"wiki-studio is installed but broken: {exc}") from exc
    except Exception as exc:  # ImportError or any error raised while the package initialises
        raise LintError(f"wiki-studio is installed but broken: {exc}") from exc
    return api


def lint_wiki(wiki_dir: Path, project_root: Path, *, require_studio: bool = False) -> LintSummary | None:
    """Run wiki-studio's lint with the health checks over the whole wiki in ``wiki_dir``.

    Returns ``None`` without the extra. Raises :class:`LintError` for every failure
    of an installed wiki-studio: a broken or incompatible package, a page that is
    not valid UTF-8, a malformed audit tree, a result whose shape memkernel does
    not recognise. The caller decides what the failure means for its own result.
    ``project_root`` is the root ``path:`` sources resolve against (memkernel's
    ``MEMKERNEL_PROJECT_ROOT``). No backend is passed, so the LLM-dependent
    contradiction check is skipped.
    """
    try:
        api = load_studio(require_studio=require_studio)
        if api is None:
            return None
        from wiki_studio.paths import WikiPaths

        result = api.lint(WikiPaths.for_root(project_root, wiki_dir=wiki_dir), health=True)
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
    except LintError as exc:  # broken installation, already wrapped by load_studio
        logger.warning("wiki-studio lint failed for %s: %s", wiki_dir, exc)
        raise
    except Exception as exc:  # third-party failure of an installed package: wrapped, never silent
        logger.warning("wiki-studio lint failed for %s: %s", wiki_dir, exc)
        raise LintError(f"wiki-studio lint failed: {exc}") from exc


class GateError(RuntimeError):
    """wiki-studio's gate rejected or failed to apply an export, or is too old to use; no page was written."""


@dataclass(frozen=True)
class GatedPage:
    """One page of an export as the gate needs it: the page itself plus its index and log lines."""

    path: str  # wiki-relative, e.g. "decisions/use-arq.md"
    content: str
    index_line: str | None  # one line of the export's single append-index edit; None = no entry
    log_line: str | None  # one line of the export's single append-log edit; None = no entry


@dataclass(frozen=True)
class GateResult:
    """What wiki-studio recorded about one promoted export (FR-005)."""

    proposal: str  # the proposal name memkernel passed to propose
    submission_digest: str | None  # None when the receipt could not be read
    archived_dir: str | None  # None when wiki-studio committed the edits but its archive step failed
    archive_hint: str | None  # how to finish an unarchived proposal; None when it was archived
    receipt_error: str | None


def _release(version: str) -> tuple[int, ...]:
    """The leading numeric release of a version string: "0.6.0rc1" -> (0, 6, 0)."""
    parts: list[int] = []
    for piece in version.split(".")[:3]:
        digits = ""
        for char in piece:
            if not char.isdigit():
                break
            digits += char
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts)


def gate_available() -> Any | None:
    """Return ``wiki_studio.api`` when it offers the proposal gate (wiki-studio >= 0.6.0), else ``None``.

    ``None`` means wiki-studio is absent, where the direct writer is the
    supported path. An installed wiki-studio that is broken, older than 0.6.0,
    or lacks the calls the bridge makes raises :class:`GateError`: the validator
    is installed, so it must not be mistaken for its absence and let pages
    through unchecked.
    """
    try:
        api = load_studio()
    except LintError as exc:
        raise GateError(str(exc)) from exc
    if api is None:
        return None
    try:
        version = metadata.version(STUDIO_DISTRIBUTION)
    except metadata.PackageNotFoundError:
        version = "unknown"
    floor = ".".join(str(part) for part in GATE_MIN_VERSION)
    missing = [name for name in ("init", "propose", "promote", "PageEdit") if not hasattr(api, name)]
    if _release(version) < GATE_MIN_VERSION or missing:
        detail = f" (missing {', '.join(missing)})" if missing else ""
        raise GateError(
            f"wiki-studio {version} is installed but the gate needs wiki-studio >= {floor}{detail}; "
            f"upgrade it (pip install 'wiki-studio>={floor},<1') or uninstall it to use the direct writer"
        )
    return api


def propose_and_promote(
    api: Any, pages: list[GatedPage], wiki_dir: Path, project_root: Path, proposals_dir: Path, name: str
) -> GateResult:
    """Write ``pages`` as one patch-set and apply it through wiki-studio's promote gate.

    A missing ``index.md`` or ``log.md`` is created first with ``api.init``
    (exclusive create, never overwrites): the gate appends to them but refuses
    to create them. Raises :class:`GateError` on any rejection or failure;
    wiki-studio validates before writing and rolls back its own writes, so a
    rejected patch-set changes no page. A scaffold ``api.init`` created stays.
    """
    # One append per file, every index line in a single append-index edit and every log line in one append-log.
    index_lines = [page.index_line for page in pages if page.index_line is not None]
    log_lines = [page.log_line for page in pages if page.log_line is not None]
    try:  # every wiki-studio call is inside the boundary, setup included, so the caller's cleanup always runs
        from wiki_studio.paths import WikiPaths

        edits = [
            api.PageEdit(path=page.path, action="create", new_content=page.content, rationale=GATE_RATIONALE)
            for page in pages
        ]
        if index_lines:
            edits.append(
                api.PageEdit(
                    path="index.md",
                    action="append-index",
                    new_content="\n".join(index_lines),
                    rationale=GATE_RATIONALE,
                )
            )
        if log_lines:
            edits.append(
                api.PageEdit(
                    path="log.md", action="append-log", new_content="\n".join(log_lines), rationale=GATE_RATIONALE
                )
            )
        paths = WikiPaths.for_root(project_root, wiki_dir=wiki_dir, proposals_dir=proposals_dir)
        api.init(paths)
        proposal = api.propose(edits, paths, name=name, source="memkernel wiki_export", backend=GATE_BACKEND)
        result = api.promote(proposal, paths)
    except Exception as exc:  # any rejection or failure of the installed gate is reported, never raised raw
        logger.warning("wiki-studio gate rejected the export to %s: %s", wiki_dir, exc)
        raise GateError(f"wiki-studio gate rejected the export: {exc}") from exc
    return _gate_result(result, name, wiki_dir, project_root, proposals_dir)


def _gate_result(result: Any, name: str, wiki_dir: Path, project_root: Path, proposals_dir: Path) -> GateResult:
    """Read the receipt where it is: the archive, or the proposal directory when the archive step failed."""
    archived = result.archived_dir
    receipt_dir = archived if archived is not None else result.proposals_dir
    hint = None
    if archived is None:
        command = shlex.join(
            [
                sys.executable,
                "-m",
                "wiki_studio",
                "--root",
                str(project_root),
                "--wiki-dir",
                str(wiki_dir),
                "--proposals-dir",
                str(proposals_dir),
                "promote",
                str(result.proposals_dir),
            ]
        )
        hint = (
            f"wiki-studio committed the export but did not archive the proposal {result.proposals_dir}; "
            f"to finish, run: {command} (it finishes the archive and applies nothing twice)"
        )
        logger.warning("wiki export to %s: %s", wiki_dir, hint)
    digest = None
    receipt_error = None
    receipt_path = receipt_dir / RECEIPT_FILE
    try:
        data = json.loads(receipt_path.read_text(encoding="utf-8"))
        value = data.get("submission_digest") if isinstance(data, dict) else None
        if not isinstance(value, str):
            raise ValueError("no submission_digest")
        digest = value
    except (OSError, ValueError) as exc:  # the export landed; an unreadable receipt is reported, never fatal
        receipt_error = f"could not read {receipt_path}: {exc}"
        logger.warning("wiki export to %s: %s", wiki_dir, receipt_error)
    return GateResult(
        proposal=name,
        submission_digest=digest,
        archived_dir=str(archived) if archived is not None else None,
        archive_hint=hint,
        receipt_error=receipt_error,
    )

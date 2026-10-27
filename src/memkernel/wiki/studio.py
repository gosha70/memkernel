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

import hashlib
import json
import logging
import re
import shlex
import sys
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

INSTALL_HINT = "install memkernel[wiki] for lint and health"
GATE_BACKEND = "memkernel"
GATE_RATIONALE = "memkernel export"
# The floor for export and import (ADR-010 addenda): 0.6.0 scopes the commit to the planned writes, rolls back on any
# exception including a write that failed part-way, and records a receipt, so memkernel keeps no snapshot.
GATE_MIN_VERSION = (0, 7, 0)  # 0.7.0 adds review state, which the governed import reads
# Every wiki-studio call the bridge makes; an installed wiki-studio without one of them is refused.
REQUIRED_CALLS = ("init", "propose", "promote", "PageEdit", "review_state", "read_page")
STUDIO_DISTRIBUTION = "wiki-studio"
RECEIPT_FILE = "receipt.json"
RECEIPT_COMMIT_STATES = ("committing", "committed")  # wiki-studio wrote the receipt before or after its commit
_PRE_RELEASE = re.compile(r"(a|b|c|rc|alpha|beta|pre|preview|dev)\d*")  # PEP 440 pre- and dev-release markers


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
    """The leading numeric release of a version string: "0.7.0rc1" -> (0, 7, 0)."""
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


def _below_floor(version: str) -> bool:
    """True when ``version`` is older than :data:`GATE_MIN_VERSION`; a pre-release of the floor (0.7.0rc1) is older."""
    release = _release(version)
    if not release:
        return True
    padded = (release + (0, 0, 0))[:3]
    if padded != GATE_MIN_VERSION:
        return padded < GATE_MIN_VERSION
    # a marker after "post" belongs to a post-release, which is above the floor (0.7.0.post1.dev2 > 0.7.0)
    return _PRE_RELEASE.search(version.split("+", 1)[0].lower().split("post", 1)[0]) is not None


def gate_available() -> Any | None:
    """Return ``wiki_studio.api`` when it offers every call the bridge makes (wiki-studio >= 0.7.0), else ``None``.

    ``None`` means wiki-studio is absent, where the direct writer is the
    supported path. An installed wiki-studio that is broken, older than 0.7.0,
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
    missing = [name for name in REQUIRED_CALLS if not hasattr(api, name)]
    if _below_floor(version) or missing:
        detail = f" (missing {', '.join(missing)})" if missing else ""
        raise GateError(
            f"wiki-studio {version} is installed but the gate needs wiki-studio >= {floor}{detail}; "
            f"upgrade it (pip install 'wiki-studio>={floor},<1') or uninstall it to use the direct writer"
        )
    return api


APPROVED_STATE = "approved"
CHANGED_SINCE_CHECK = "live_bytes_differ_from_approved"  # read_page's bytes are not the approved revision


@dataclass(frozen=True)
class PageReview:
    """One page's review state; for an importable page, the approved revision's text from a single read."""

    path: str  # wiki-relative
    page_key: str  # wiki-studio's page_id, else the normalised path
    state: str
    reason: str
    text: str | None = None  # set only when the page is importable
    sha256: str | None = None


def review_pages(api: Any, wiki_dir: Path, project_root: Path) -> list[PageReview]:
    """Every page's review state (memkernel-0-6 FR-010).

    A page is importable only when ``review_state`` reports it approved and the
    bytes ``read_page`` returns have the approved sha256; its text comes from
    that same read, so an edit made after the check is never imported. Raises
    :class:`GateError` on any failure of the installed wiki-studio.
    """
    try:
        from wiki_studio.paths import WikiPaths

        paths = WikiPaths.for_root(project_root, wiki_dir=wiki_dir)
        reviews: list[PageReview] = []
        for state in api.review_state(paths):
            if state.state != APPROVED_STATE:
                reviews.append(PageReview(state.path, state.page_key, state.state, state.reason))
                continue
            read = api.read_page(state.path, paths)
            if read.sha256 != state.approved_sha256:
                reviews.append(PageReview(state.path, state.page_key, state.state, CHANGED_SINCE_CHECK))
                continue
            reviews.append(PageReview(state.path, state.page_key, state.state, state.reason, read.text, read.sha256))
    except Exception as exc:  # any failure of the installed wiki-studio is reported, never raised raw
        logger.warning("wiki-studio review state failed for %s: %s", wiki_dir, exc)
        raise GateError(f"wiki-studio review state failed: {exc}") from exc
    return reviews


def propose_and_promote(
    api: Any, pages: list[GatedPage], wiki_dir: Path, project_root: Path, proposals_dir: Path, name: str
) -> GateResult:
    """Write ``pages`` as one patch-set and apply it through wiki-studio's promote gate.

    A missing ``index.md`` or ``log.md`` is created first with ``api.init``
    (exclusive create, never overwrites): the gate appends to them but refuses
    to create them. Raises :class:`GateError` on any rejection or failure,
    except when wiki-studio raised after it had committed the pages (FR-009):
    that is returned as a result with the hint that finishes it. wiki-studio
    validates before writing and rolls back its own writes, so a rejected
    patch-set changes no page. A scaffold ``api.init`` created stays.
    """
    # One append per file, every index line in a single append-index edit and every log line in one append-log.
    index_lines = [page.index_line for page in pages if page.index_line is not None]
    log_lines = [page.log_line for page in pages if page.log_line is not None]
    proposal: Path | None = None
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
        if proposal is not None:
            landed = _committed_then_failed(exc, Path(proposal), pages, paths, name)
            if landed is not None:
                return landed
        logger.warning("wiki-studio gate rejected the export to %s: %s", wiki_dir, exc)
        raise GateError(f"wiki-studio gate rejected the export: {exc}") from exc
    return _gate_result(result, name, paths)


def _finish_hint(paths: Any, proposal_dir: Path, what: str) -> str:
    """The promote command that finishes ``proposal_dir``, built from ``paths`` (``WikiPaths``, absolute against
    the server's working directory) so it can be run from any directory, through memkernel's own interpreter."""
    command = shlex.join(
        [
            sys.executable,
            "-m",
            "wiki_studio",
            "--root",
            str(paths.root),
            "--wiki-dir",
            str(paths.wiki_dir),
            "--proposals-dir",
            str(paths.proposals_dir),
            "promote",
            str(proposal_dir.absolute()),
        ]
    )
    return f"{what}; to finish, run: {command} (it finishes the archive and applies nothing twice)"


def _read_receipt(receipt_path: Path) -> dict[str, Any]:
    data = json.loads(receipt_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("not a JSON object")
    return data


def _digest(receipt: dict[str, Any]) -> str:
    value = receipt.get("submission_digest")
    if not isinstance(value, str):
        raise ValueError("no submission_digest")
    return value


def _committed_then_failed(
    exc: Exception, proposal_dir: Path, pages: list[GatedPage], paths: Any, name: str
) -> GateResult | None:
    """FR-009: the GateResult of an export wiki-studio committed before it raised, or None when it did not commit.

    The evidence is wiki-studio's own record: the receipt in ``proposal_dir`` (state ``committing`` or
    ``committed``) and, for every page memkernel created, an on-disk sha256 equal to the receipt's
    ``post_sha256``. A missing receipt means no commit. Only when the receipt exists but cannot be read are
    the pages' bytes compared with what memkernel proposed. memkernel never promotes again itself; the hint
    tells the user how.
    """
    receipt_path = proposal_dir / RECEIPT_FILE
    if not receipt_path.exists() and not receipt_path.is_symlink():
        return None  # wiki-studio writes its committing receipt before any wiki write: no receipt, no commit
    receipt: dict[str, Any] | None = None
    receipt_error = None
    try:
        receipt = _read_receipt(receipt_path)
        post = {str(w["path"]): str(w["post_sha256"]) for w in receipt["planned_writes"]}
    except (OSError, ValueError, KeyError, TypeError) as error:
        post = None
        receipt_error = f"could not read {receipt_path}: {error}"
    try:
        if post is not None and receipt is not None:
            landed = receipt.get("state") in RECEIPT_COMMIT_STATES and all(
                page.path in post and _sha256_file(paths.wiki_dir / page.path) == post[page.path] for page in pages
            )
        else:
            landed = all((paths.wiki_dir / page.path).read_bytes() == page.content.encode("utf-8") for page in pages)
    except OSError:
        landed = False
    if not pages or not landed:
        return None
    digest = None
    if receipt is not None:
        try:
            digest = _digest(receipt)
        except ValueError as error:
            receipt_error = f"could not read {receipt_path}: {error}"
    hint = _finish_hint(paths, proposal_dir, f"wiki-studio committed the export, then failed ({exc})")
    logger.warning("wiki export to %s: %s", paths.wiki_dir, hint)
    if receipt_error is not None:
        logger.warning("wiki export to %s: %s", paths.wiki_dir, receipt_error)
    return GateResult(
        proposal=name, submission_digest=digest, archived_dir=None, archive_hint=hint, receipt_error=receipt_error
    )


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _gate_result(result: Any, name: str, paths: Any) -> GateResult:
    """Read the receipt where it is: the archive, or the proposal directory when the archive step failed."""
    archived = result.archived_dir
    receipt_dir = archived if archived is not None else result.proposals_dir
    hint = None
    if archived is None:
        hint = _finish_hint(
            paths,
            result.proposals_dir,
            f"wiki-studio committed the export but did not archive the proposal {result.proposals_dir}",
        )
        logger.warning("wiki export to %s: %s", paths.wiki_dir, hint)
    digest = None
    receipt_error = None
    receipt_path = receipt_dir / RECEIPT_FILE
    try:
        digest = _digest(_read_receipt(receipt_path))
    except (OSError, ValueError) as exc:  # the export landed; an unreadable receipt is reported, never fatal
        receipt_error = f"could not read {receipt_path}: {exc}"
        logger.warning("wiki export to %s: %s", paths.wiki_dir, receipt_error)
    return GateResult(
        proposal=name,
        submission_digest=digest,
        archived_dir=str(archived) if archived is not None else None,
        archive_hint=hint,
        receipt_error=receipt_error,
    )

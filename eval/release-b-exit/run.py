# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""The Release B exit run (#48; specs/memkernel-0-7-release-b-exit): one correction loop, surviving retries.

``python run.py --workdir DIR [--summary PATH]`` runs the main run. ``python run.py --upgrade --upgrade-to REQ
--workdir DIR [--summary PATH]`` runs the upgrade run (E7): it starts in an environment holding memkernel 0.6.0,
and installs ``REQ`` (the 0.7.x wheel or requirement) into this interpreter's environment halfway through.

Every step is its own process (``run.py step NAME``) on one persisted memkernel store and one governed wiki under
``DIR``. The orchestrator never imports memkernel or wiki-studio, so the upgrade run can change the installed
memkernel between steps. Faults (R1–R4) are injected only inside a step's own process, by wrapping a function
before the step calls memkernel or wiki-studio; the installed packages' files are never patched.

Exit codes: 0 when every check passes; 1 when a check fails (one line names it); 2 when the run cannot start.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import traceback
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PROJECT_ID = "memkernel-release-b-exit"
CURATOR = "curator"
QUESTION = "When may we deploy?"
TOPIC, WRONG, RIGHT = "Deploy window", "Deploy on Fridays after 17:00 UTC.", "Deploy on Tuesdays before noon."
# The memories session 1 retains, by role: (first line, rule). The first line names the topic, so it is the title.
MEMORIES = {
    "wrong": (TOPIC, WRONG),
    "deprecate": ("Cache layer", "Put memcached in front of the user API."),
    "delete": ("Log format", "Write plain-text logs to /var/log/app.log."),
    "supersede": ("Job queue", "Use RabbitMQ for background jobs."),
    "edit": ("Database", "Use Postgres 14 for the user database."),
}
EDITED_RULE = "Use Postgres 16 for the user database."
SUCCESSOR_SLUG, SUCCESSOR_TITLE, SUCCESSOR_RULE = "job-queue-arq", "Job queue on arq", "Use arq for background jobs."
UPGRADE_MEMORIES = {"wrong": (TOPIC, WRONG), "other": ("Code review", "Every change needs one reviewer.")}

STATE_DIR = ".exit"
R4_HOLD_SECONDS = 1.0
WAIT_SECONDS = 120.0
MAIN_STEPS = ("session-1", "curator-1", "session-2", "session-2-again", "curator-2", "session-3", "session-4")
UPGRADE_STEPS_06 = ("u-session-0",)
UPGRADE_STEPS_07 = ("u-session-1", "u-session-2", "u-curator", "u-session-3")


class CannotRunError(Exception):
    """The run cannot start: a missing package, CLI or model, or a bad argument (exit 2)."""


class CheckFailedError(Exception):
    """A named check failed (exit 1)."""

    def __init__(self, name: str, detail: str = "") -> None:
        super().__init__(name)
        self.name = name
        self.detail = detail


# ── the shared state between steps ───────────────────────────────────────────


def _state_file(workdir: Path) -> Path:
    return workdir / STATE_DIR / "state.json"


def _load(workdir: Path) -> dict[str, Any]:
    path = _state_file(workdir)
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def _save(workdir: Path, step: str, values: dict[str, Any], checks: list[dict[str, Any]]) -> None:
    state = _load(workdir)
    state[step] = {"values": values, "checks": checks}
    _state_file(workdir).parent.mkdir(parents=True, exist_ok=True)
    _state_file(workdir).write_text(json.dumps(state, indent=2, default=str) + "\n", encoding="utf-8")


def _values(workdir: Path, step: str) -> dict[str, Any]:
    state = _load(workdir)
    if step not in state:
        raise CannotRunError(f"{step} has not run in this --workdir")
    return dict(state[step]["values"])


def _check(checks: list[dict[str, Any]], name: str, ok: bool, detail: str = "") -> None:
    """Record one check; a false one stops the step, naming it."""
    checks.append({"name": name, "ok": bool(ok), "detail": detail})
    if not ok:
        raise CheckFailedError(name, detail)
    print(f"ok: {name}", flush=True)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _marker(workdir: Path, name: str) -> Path:
    return workdir / STATE_DIR / "markers" / name


def _mark(workdir: Path, name: str, value: str = "") -> None:
    path = _marker(workdir, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value or repr(time.time()), encoding="utf-8")


def _wait_for(workdir: Path, name: str, timeout: float = WAIT_SECONDS) -> str:
    deadline = time.monotonic() + timeout
    while not _marker(workdir, name).exists():
        if time.monotonic() > deadline:
            raise CheckFailedError("marker-reached", f"timed out waiting for {name}")
        time.sleep(0.02)
    return _marker(workdir, name).read_text(encoding="utf-8")


# ── the environment every step runs in ───────────────────────────────────────


def _env(workdir: Path, governed: bool = True) -> dict[str, str]:
    env = os.environ.copy()
    for name in [k for k in env if k.startswith(("MEMKERNEL_", "WIKI_STUDIO_"))]:
        if name not in ("MEMKERNEL_EMBEDDING_MODEL",):
            env.pop(name)
    env["WIKI_STUDIO_ROOT"] = str(workdir)
    env["MEMKERNEL_PROJECT_ID"] = PROJECT_ID
    env["MEMKERNEL_PROJECT_ROOT"] = str(workdir)
    env["MEMKERNEL_CHROMA_PERSIST_PATH"] = str(workdir / ".memkernel" / "chroma")
    env["MEMKERNEL_WIKI_DIR"] = str(workdir / "knowledge" / "wiki")
    env["MEMKERNEL_WIKI_PROPOSALS_DIR"] = str(workdir / "doc_internal" / "proposals")
    if governed:  # memkernel 0.7 settings; memkernel 0.6.0 would only warn about them
        env["MEMKERNEL_STATE_DIR"] = str(workdir / ".memkernel" / "state")
        env["MEMKERNEL_WIKI_MODE"] = "governed"
    return env


def _cli() -> str:
    cli = shutil.which("wiki-studio", path=str(Path(sys.executable).parent))
    if cli is None:
        raise CannotRunError(f"the wiki-studio CLI is not beside the interpreter ({Path(sys.executable).parent})")
    return cli


def _run_cli(workdir: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([_cli(), *args], cwd=str(workdir), capture_output=True, text=True, check=False)  # noqa: S603


def _tail(text: str, limit: int = 400) -> str:
    return " ".join(text.split())[-limit:]


# ── memkernel and wiki-studio, inside a step ─────────────────────────────────


def _service() -> Any:
    from memkernel.factory import build_service

    return build_service()


def _settings() -> Any:
    from memkernel.config import MemKernelSettings

    return MemKernelSettings()


def _paths() -> Any:
    from wiki_studio.paths import WikiPaths

    return WikiPaths.resolve()


def _export(service: Any) -> Any:
    from memkernel.wiki.sync import WikiExporter

    settings = _settings()  # memkernel 0.6.0's MemoryService has no .settings
    return WikiExporter(
        service,
        Path(settings.wiki_dir),
        project_root=Path(settings.project_root),
        proposals_dir=Path(settings.wiki_proposals_dir),
    ).export()


def _import(service: Any, **adopt: Any) -> Any:
    from memkernel.wiki.sync import WikiImporter

    settings = _settings()  # memkernel 0.6.0's MemoryService has no .settings
    return WikiImporter(service, Path(settings.wiki_dir), project_root=Path(settings.project_root)).import_pages(
        **adopt
    )


def _wiki_memories(service: Any, include_retired: bool = False) -> list[Any]:
    from memkernel.core.models import MemoryTier

    memories = service.list_memories(tier=MemoryTier.LONG_TERM, include_superseded=include_retired)
    return [m for m in memories if "wiki" in m.tags]


def _slug(first_line: str) -> str:
    from memkernel.wiki.pages import slugify

    return str(slugify(first_line))


def _page(role: str, memories: dict[str, tuple[str, str]] = MEMORIES) -> str:
    return f"decisions/{_slug(memories[role][0])}.md"


def _set_governed(wiki_dir: Path) -> None:
    """The wiki's manifest policy requires approval: wiki-studio's ``governed`` mode."""
    manifest = wiki_dir / ".wiki-studio.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["policy"]["approval_required"] = True
    manifest.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _replace_one(lines: list[str], old: str, new: str, check: str) -> None:
    hits = [index for index, line in enumerate(lines) if line == old]
    if len(hits) != 1:
        raise CheckFailedError(check, f"expected one line {old!r}, found {len(hits)}")
    lines[hits[0]] = new


def _with_status(text: str, old: str, new: str, extra: list[str] | None = None) -> str:
    lines = text.splitlines()
    _replace_one(lines, f"status: {old}", f"status: {new}", "page-edited")
    if extra:
        index = lines.index(f"status: {new}")
        lines[index + 1 : index + 1] = extra
    return "\n".join(lines) + "\n"


def _corrected(text: str, wrong_ref: str) -> str:
    """The curator's correction: the rule replaced in the title, the heading and the body, and ``corrects:``."""
    text = _with_status(text, "draft", "stable", [f"corrects: {wrong_ref}"])
    lines = text.splitlines()
    _replace_one(lines, f"title: {TOPIC}", f"title: {RIGHT}", "correction-drafted")
    _replace_one(lines, f"# {TOPIC}", f"# {RIGHT}", "correction-drafted")
    _replace_one(lines, TOPIC, RIGHT, "correction-drafted")
    _replace_one(lines, WRONG, RIGHT, "correction-drafted")
    return "\n".join(lines) + "\n"


def _propose_from(workdir: Path, name: str, pages: dict[str, str], checks: list[dict[str, Any]]) -> None:
    """The curator's guarded updates: the pages in a draft directory outside the wiki, with ``.base.json``."""
    draft_dir = workdir / "drafts" / name
    bases = {}
    for rel, text in pages.items():
        read = _run_cli(workdir, "read", "--json", rel)
        _check(checks, f"{name}-read-{rel}", read.returncode == 0, _tail(read.stderr))
        bases[rel] = json.loads(read.stdout)["sha256"]
        (draft_dir / rel).parent.mkdir(parents=True, exist_ok=True)
        (draft_dir / rel).write_text(text, encoding="utf-8")
    (draft_dir / ".base.json").write_text(json.dumps(bases), encoding="utf-8")
    propose = _run_cli(workdir, "propose", "--from", str(draft_dir.relative_to(workdir)), "--promote", "--by", CURATOR)
    _check(checks, f"{name}-promoted", propose.returncode == 0, _tail(propose.stderr or propose.stdout))


def _approve(workdir: Path, pages: list[str], checks: list[dict[str, Any]], name: str) -> None:
    approve = _run_cli(workdir, "approve", *pages, "--by", CURATOR)
    _check(checks, f"{name}-approved", approve.returncode == 0, _tail(approve.stderr or approve.stdout))


def _read(rel: str) -> str:
    from wiki_studio import api

    return str(api.read_page(rel, _paths()).text)


def _review(rel: str) -> Any:
    from wiki_studio import api

    return api.review_state(_paths(), pages=[rel])[0]


def _unfinished_ledger_entries(workdir: Path) -> int:
    base = workdir / ".memkernel" / "state" / "wiki-sync" / PROJECT_ID
    count = 0
    for path in base.glob("*.json"):
        entries = json.loads(path.read_text(encoding="utf-8")).get("entries", {})
        count += sum(1 for entry in entries.values() if entry.get("state") in ("pending", "failed"))
    return count


def _converged(
    workdir: Path,
    service: Any,
    checks: list[dict[str, Any]],
    live: dict[str, str],
    retired: dict[str, str],
    name: str,
    files: set[str],
) -> dict[str, Any]:
    """The convergence checks (plan.md, Retries): the expected live pages and retired records, no page key with
    two live memories, no duplicate page or receipt, no unfinished ledger entry. ``live`` maps a page to a rule
    its live wiki memory holds; ``retired`` maps a rule to "superseded" or "withdrawn": a retired record holding it
    is kept. A page's withdrawal retires the page's memory only; the agent's own memory with the same rule stays
    live unless a page ``corrects`` it."""
    memories = _wiki_memories(service)
    by_source: dict[str, list[Any]] = {}
    for memory in memories:
        by_source.setdefault(memory.source, []).append(memory)
    keys: dict[str, int] = {}
    for memory in memories:
        for tag in memory.tags:
            if tag.startswith("page_key:"):
                keys[tag] = keys.get(tag, 0) + 1
    _check(checks, f"{name}-live-pages", sorted(by_source) == sorted(live), str(sorted(by_source)))
    _check(
        checks,
        f"{name}-live-content",
        all(len(by_source[rel]) == 1 and rule in by_source[rel][0].content for rel, rule in live.items()),
        str({rel: [m.content[:60] for m in found] for rel, found in by_source.items()}),
    )
    _check(checks, f"{name}-one-live-memory-per-page-key", all(count == 1 for count in keys.values()), str(keys))
    every = service.list_memories(include_superseded=True)  # the corrected rule's record is the agent's own memory
    outcome: dict[str, str] = {}
    for rule, how in retired.items():
        held = [m for m in every if rule in m.content and m.retired()]
        state = "superseded" if any(m.superseded_by for m in held) else "withdrawn" if held else "absent"
        if how == "withdrawn" and any(getattr(m, "withdrawn_reason", None) for m in held):
            state = "withdrawn"
        outcome[rule] = state
    _check(checks, f"{name}-retired-records-kept", outcome == retired, str(outcome))
    wiki = Path(_settings().wiki_dir)
    page_files = sorted(
        p.relative_to(wiki).as_posix()
        for p in wiki.rglob("*.md")
        if not any(part.startswith(".") for part in p.relative_to(wiki).parts)  # not .audit/, wiki-studio's trail
    )
    _check(checks, f"{name}-exact-page-set", page_files == sorted(files), str(page_files))
    page_ids = [
        line.split(":", 1)[1].strip()
        for rel in page_files
        if rel not in ("index.md", "log.md")
        for line in (wiki / rel).read_text(encoding="utf-8").splitlines()
        if line.startswith("page_id:")
    ]
    _check(checks, f"{name}-unique-page-ids", len(page_ids) == len(set(page_ids)), str(page_ids))
    targets = re.findall(r"\]\(([^)]+\.md)\)", (wiki / "index.md").read_text(encoding="utf-8"))
    _check(checks, f"{name}-unique-index-entries", len(targets) == len(set(targets)), str(targets))
    applied = workdir / "doc_internal" / "proposals" / ".applied"
    digests = [
        json.loads(r.read_text(encoding="utf-8")).get("submission_digest") for r in applied.glob("*/receipt.json")
    ]
    _check(checks, f"{name}-no-duplicate-receipt", len(digests) == len(set(digests)), str(len(digests)))
    unfinished = _unfinished_ledger_entries(workdir)
    _check(checks, f"{name}-no-unfinished-ledger-entry", unfinished == 0, str(unfinished))
    return {
        "live": {rel: [m.content.splitlines()[0] for m in found] for rel, found in sorted(by_source.items())},
        "retired": outcome,
        "receipts": len(digests),
        "ledger_unfinished": unfinished,
    }


# ── the main run's steps ─────────────────────────────────────────────────────


def _session_1(workdir: Path, checks: list[dict[str, Any]], values: dict[str, Any]) -> None:
    """Initialise a governed wiki; retain five decisions; export them as drafts; the debt shows them."""
    from wiki_studio import api

    from memkernel.core.models import MemoryType
    from memkernel.lifecycle import MemoryLifecycle

    paths = _paths()
    api.init(paths)
    _set_governed(paths.wiki_dir)
    _check(checks, "wiki-governed", api.info(paths).manifest.mode == "governed")
    service = _service()
    refs = {role: service.retain(f"{line}\n\n{rule}", MemoryType.DECISION) for role, (line, rule) in MEMORIES.items()}
    _check(checks, "decisions-retained", all(refs.values()) and len(set(refs.values())) == len(MEMORIES))
    recalled = [service.get(r.ref_id, touch=False) for r in service.recall(QUESTION)]
    _check(checks, "wrong-rule-current", any(m is not None and WRONG in m.content for m in recalled))
    report = _export(service)
    _check(checks, "export-gated-governed", report.gated and report.mode == "gated" and report.gate_error is None)
    _check(checks, "export-configured-governed", report.configured_mode == "governed", report.configured_mode)
    _check(checks, "five-draft-pages", sorted(report.written) == sorted(_page(r) for r in MEMORIES))
    _check(checks, "nothing-remaining", report.remaining == 0, str(report.remaining))
    _check(checks, "pages-carry-page-id", all("page_id: pg-" in _read(rel) for rel in report.written))
    block = MemoryLifecycle(service, _settings()).on_session_start("startup")
    _check(checks, "curation-debt-shows-the-drafts", "### Curation debt\nunapproved 5" in block, _tail(block))
    values.update({"refs": refs, "pages": {role: _page(role) for role in MEMORIES}})


def _curator_1(workdir: Path, checks: list[dict[str, Any]], values: dict[str, Any]) -> None:
    """Correct the wrong page (``corrects:``), make the rest stable, approve all five."""
    session_1 = _values(workdir, "session-1")
    pages, refs = session_1["pages"], session_1["refs"]
    edits = {}
    for role, rel in pages.items():
        text = _read(rel)
        edits[rel] = _corrected(text, refs["wrong"]) if role == "wrong" else _with_status(text, "draft", "stable")
    _propose_from(workdir, "curator-1", edits, checks)
    _approve(workdir, list(pages.values()), checks, "curator-1")
    reviews = {rel: _review(rel) for rel in pages.values()}
    _check(checks, "all-approved", all(r.state == "approved" for r in reviews.values()), str(reviews))
    values["approved_sha256"] = reviews[pages["wrong"]].approved_sha256


def _session_2(workdir: Path, checks: list[dict[str, Any]], values: dict[str, Any]) -> None:
    """R4's two imports at once: this process is the first or the second, by ``EXIT_R4_ROLE``."""
    from memkernel.core.services import MemoryService

    role = os.environ["EXIT_R4_ROLE"]
    real_retain, real_exclusive = MemoryService.retain, MemoryService.exclusive

    if role == "first":

        def retain(self: Any, *args: Any, **kwargs: Any) -> Any:
            ref = real_retain(self, *args, **kwargs)
            if not _marker(workdir, "r4-first-wrote").exists():
                _mark(workdir, "r4-first-wrote")
                _wait_for(workdir, "r4-release")  # held inside the import lock
            return ref

        MemoryService.retain = retain  # type: ignore[method-assign]
    else:
        from contextlib import contextmanager

        @contextmanager
        def exclusive(self: Any, name: str) -> Any:
            if not _marker(workdir, "r4-second-reached").exists():
                _mark(workdir, "r4-second-reached")  # the import asks for the store's lock now
            with real_exclusive(self, name):
                if not _marker(workdir, "r4-second-locked").exists():
                    _mark(workdir, "r4-second-locked")
                yield

        MemoryService.exclusive = exclusive  # type: ignore[method-assign]
    service = _service()
    report = _import(service)
    values.update(
        {
            "role": role,
            "governed": report.governed,
            "imported": report.imported,
            "unchanged": report.unchanged,
            "corrections": report.corrections,
            "import_error": report.import_error,
            "mode": report.mode,
        }
    )
    _check(checks, f"r4-{role}-import-ran", report.import_error is None, str(report.import_error))


def _session_2_check(workdir: Path, checks: list[dict[str, Any]], values: dict[str, Any]) -> None:
    """After R4: the lock serialized the two imports, and the store converged."""
    first, second = _values(workdir, "session-2-first"), _values(workdir, "session-2-second")
    released = float(_marker(workdir, "r4-release").read_text(encoding="utf-8"))
    reached = float(_marker(workdir, "r4-second-reached").read_text(encoding="utf-8"))
    locked = float(_marker(workdir, "r4-second-locked").read_text(encoding="utf-8"))
    _check(checks, "r4-second-reached-before-release", reached < released, f"{reached} < {released}")
    _check(checks, "r4-second-locked-after-release", locked >= released, f"{locked} >= {released}")
    session_1 = _values(workdir, "session-1")
    pages, refs = session_1["pages"], session_1["refs"]
    _check(checks, "first-imported-all", sorted(first["imported"]) == sorted(pages.values()), str(first["imported"]))
    _check(checks, "second-found-all-current", second["imported"] == [] and len(second["unchanged"]) == len(pages))
    _check(
        checks,
        "correction-recorded",
        [c["ref_id"] for c in first["corrections"]] == [refs["wrong"]],
        str(first["corrections"]),
    )
    service = _service()
    live = {rel: (RIGHT if role == "wrong" else MEMORIES[role][1]) for role, rel in pages.items()}
    files = {*pages.values(), "index.md", "log.md"}
    values["summary"] = _converged(workdir, service, checks, live, {WRONG: "superseded"}, "session-2", files)


def _session_2_again(workdir: Path, checks: list[dict[str, Any]], values: dict[str, Any]) -> None:
    """R3: export and import again change nothing."""
    service = _service()
    before = _values(workdir, "session-2-check")["summary"]
    again = _export(service)
    _check(checks, "r3-export-again-writes-nothing", again.written == [] and again.gate_error is None)
    report = _import(service)
    _check(checks, "r3-import-again-imports-nothing", report.imported == [] and report.import_error is None)
    session_1 = _values(workdir, "session-1")
    live = {rel: (RIGHT if role == "wrong" else MEMORIES[role][1]) for role, rel in session_1["pages"].items()}
    files = {*session_1["pages"].values(), "index.md", "log.md"}
    summary = _converged(workdir, service, checks, live, {WRONG: "superseded"}, "r3", files)
    _check(checks, "r3-same-summary", summary == before, json.dumps(summary))


def _curator_2(workdir: Path, checks: list[dict[str, Any]], values: dict[str, Any]) -> None:
    """R1 on the successor's promote; then deprecate, supersede, edit and delete one page each."""
    from unittest.mock import patch

    from wiki_studio import api, promoter

    pages = _values(workdir, "session-1")["pages"]
    paths = _paths()
    successor = f"decisions/{SUCCESSOR_SLUG}.md"
    template = _read(pages["supersede"]).splitlines()
    kept = [
        line
        for line in template
        if not line.startswith(("page_id:", "memkernel_ref:", "memory_type:", "memkernel_sha256:"))
    ]
    old_slug, old_title = _slug(MEMORIES["supersede"][0]), MEMORIES["supersede"][0]
    text = "\n".join(kept) + "\n"
    for old, new in (
        (f"slug: {old_slug}", f"slug: {SUCCESSOR_SLUG}"),
        (f"title: {old_title}", f"title: {SUCCESSOR_TITLE}"),
        (f"# {old_title}", f"# {SUCCESSOR_TITLE}"),
        (MEMORIES["supersede"][1], SUCCESSOR_RULE),
    ):
        text = text.replace(old, new, 1)
    edits = [
        api.PageEdit(path=successor, action="create", new_content=text, rationale="successor"),
        api.PageEdit(
            path="index.md",
            action="append-index",
            new_content=f"- [{SUCCESSOR_TITLE}]({successor}) — supersedes the RabbitMQ decision.",
            rationale="successor",
        ),
    ]
    # R1: the promote commits, then its archive step fails; promoting again resolves from the receipt.
    proposal = api.propose(edits, paths, name="curator-2-successor", assign_page_ids=True, by=CURATOR)
    with patch.object(promoter, "_archive_submission", side_effect=OSError(5, "I/O error")):
        try:
            api.promote(proposal, paths, by=CURATOR)
        except Exception as exc:  # wiki-studio reports the failed archive after its commit
            print(f"r1: the promote failed after its commit: {exc}", flush=True)
    leftover = Path(proposal).is_dir() and not (Path(paths.proposals_dir) / ".applied" / Path(proposal).name).exists()
    _check(checks, "r1-archive-failed", leftover, str(proposal))  # the fault happened: the proposal is not archived
    receipt = json.loads((Path(proposal) / "receipt.json").read_text(encoding="utf-8"))
    _check(checks, "r1-committed-before-the-failure", receipt.get("state") == "committed", str(receipt.get("state")))
    tree = {p: p.read_bytes() for p in sorted(paths.wiki_dir.rglob("*.md"))}
    result = api.promote(proposal, paths, by=CURATOR)
    _check(checks, "r1-resolved-from-the-receipt", result.archived_dir is not None)
    _check(checks, "r1-nothing-reapplied", tree == {p: p.read_bytes() for p in sorted(paths.wiki_dir.rglob("*.md"))})
    _approve(workdir, [successor], checks, "successor")

    edits_by_page = {
        pages["deprecate"]: _with_status(_read(pages["deprecate"]), "stable", "deprecated"),
        pages["supersede"]: _with_status(
            _read(pages["supersede"]), "stable", "stable", [f"superseded_by: {successor}"]
        ),
        pages["edit"]: _read(pages["edit"]).replace(MEMORIES["edit"][1], EDITED_RULE),
    }
    _propose_from(workdir, "curator-2", edits_by_page, checks)
    _approve(workdir, [pages["deprecate"], pages["edit"]], checks, "curator-2")
    # Deletion: the curator removes the page and its index entry, as a git commit would.
    (paths.wiki_dir / pages["delete"]).unlink()
    index = paths.wiki_dir / "index.md"
    index.write_text(
        "".join(
            line for line in index.read_text(encoding="utf-8").splitlines(True) if f"]({pages['delete']})" not in line
        ),
        encoding="utf-8",
    )
    _check(checks, "page-deleted", not (paths.wiki_dir / pages["delete"]).exists())
    values["successor"] = successor


def _session_3_killed(workdir: Path, checks: list[dict[str, Any]], values: dict[str, Any]) -> None:
    """R2: killed between the edited page's replacement write and its predecessor's supersession mark."""
    from memkernel.core.services import MemoryService

    service = _service()
    edit_page = _values(workdir, "session-1")["pages"]["edit"]
    (predecessor,) = [m for m in _wiki_memories(service) if m.source == edit_page]
    real = MemoryService._mark_superseded

    def mark(self: Any, target_ref: str, by_ref: str) -> None:
        if target_ref == predecessor.ref_id:
            _mark(workdir, "r2-killed", json.dumps({"predecessor": target_ref, "replacement": by_ref}))
            os._exit(0)  # no finally runs: nothing else is saved
        real(self, target_ref, by_ref)

    MemoryService._mark_superseded = mark  # type: ignore[method-assign]
    _import(service)
    _check(checks, "r2-killed", False, "the import finished without reaching the predecessor's mark")


def _session_3(workdir: Path, checks: list[dict[str, Any]], values: dict[str, Any]) -> None:
    """After R2's kill: both records live; the next import completes the supersession and the withdrawals."""
    killed = json.loads(_marker(workdir, "r2-killed").read_text(encoding="utf-8"))
    service = _service()
    pages = _values(workdir, "session-1")["pages"]
    live_before = {m.ref_id for m in _wiki_memories(service)}
    _check(
        checks,
        "r2-both-live-after-the-kill",
        {killed["predecessor"], killed["replacement"]} <= live_before,
        json.dumps(killed),
    )
    report = _import(service)
    _check(checks, "import-completed", report.import_error is None and report.sync_failed == [])
    withdrawn = sorted((w["path"], w["reason"]) for w in report.withdrawn)
    _check(
        checks,
        "deprecated-and-deleted-withdrawn",
        withdrawn == sorted([(pages["deprecate"], "deprecated"), (pages["delete"], "deleted")]),
        str(report.withdrawn),
    )
    _check(
        checks,
        "superseded-by-the-successor",
        [s["path"] for s in report.superseded] == [pages["supersede"]],
        str(report.superseded),
    )
    predecessor = service.get(killed["predecessor"], touch=False)
    _check(
        checks,
        "r2-supersession-completed",
        predecessor is not None and predecessor.superseded_by == killed["replacement"],
        str(predecessor.superseded_by if predecessor else None),
    )
    successor = _values(workdir, "curator-2")["successor"]
    live = {pages["wrong"]: RIGHT, pages["edit"]: EDITED_RULE, successor: SUCCESSOR_RULE}
    retired = {
        WRONG: "superseded",
        MEMORIES["deprecate"][1]: "withdrawn",
        MEMORIES["delete"][1]: "withdrawn",
        MEMORIES["supersede"][1]: "superseded",
        MEMORIES["edit"][1]: "superseded",
    }
    files = {pages["wrong"], pages["edit"], pages["deprecate"], pages["supersede"], successor, "index.md", "log.md"}
    values["summary"] = _converged(workdir, service, checks, live, retired, "session-3", files)


def _session_4(workdir: Path, checks: list[dict[str, Any]], values: dict[str, Any]) -> None:
    """The next session: the start block and recall answer with the corrected page only."""
    from memkernel.lifecycle import MemoryLifecycle

    service = _service()
    pages = _values(workdir, "session-1")["pages"]
    block = MemoryLifecycle(service, _settings()).on_session_start("startup")
    _check(checks, "start-block-has-no-wrong-rule", WRONG not in block)
    _check(checks, "start-block-no-unapproved-debt", "unapproved" not in block, _tail(block))
    recalled = [service.get(r.ref_id, touch=False) for r in service.recall(QUESTION)]
    answers = [m for m in recalled if m is not None and RIGHT in m.content]
    _check(checks, "right-answer-current", bool(answers))
    _check(checks, "wrong-rule-not-current", not any(m is not None and WRONG in m.content for m in recalled))
    answer = answers[0]
    review = _review(pages["wrong"])
    page_sha = [t.split(":", 1)[1] for t in answer.tags if t.startswith("page_sha:")]
    _check(checks, "answer-is-the-approved-revision", review.approved_sha256 in page_sha, str(page_sha))
    values.update({"answer": answer.content, "page": answer.source, "approved_sha256": review.approved_sha256})
    print(f"answer: {answer.content.splitlines()[0]}")


# ── the upgrade run's steps (E7) ─────────────────────────────────────────────


def _u_session_0(workdir: Path, checks: list[dict[str, Any]], values: dict[str, Any]) -> None:
    """On memkernel 0.6.0: retain, export, approve, import: a store 0.6.0 itself wrote."""
    from importlib import metadata

    from wiki_studio import api

    from memkernel.core.models import MemoryType

    version = metadata.version("memkernel")
    _check(checks, "memkernel-0.6.0", version == "0.6.0" and not _has_0_7(), version)
    paths = _paths()
    api.init(paths)
    _set_governed(paths.wiki_dir)
    service = _service()
    refs = {r: service.retain(f"{line}\n\n{rule}", MemoryType.DECISION) for r, (line, rule) in UPGRADE_MEMORIES.items()}
    report = _export(service)
    _check(checks, "0.6-export-gated", report.gated and len(report.written) == len(refs), str(report.gate_error))
    edits = {rel: _with_status(_read(rel), "draft", "stable") for rel in report.written}
    _propose_from(workdir, "u-curator-0", edits, checks)
    _approve(workdir, list(report.written), checks, "u-curator-0")
    imported = _import(service)
    _check(checks, "0.6-import-governed", imported.governed and len(imported.imported) == len(refs))
    pages = {r: _page(r, UPGRADE_MEMORIES) for r in UPGRADE_MEMORIES}
    wiki_refs = {m.source: m.ref_id for m in _wiki_memories(service)}
    _check(checks, "0.6-wiki-memories", sorted(wiki_refs) == sorted(pages.values()), str(sorted(wiki_refs)))
    values.update({"refs": refs, "pages": pages, "wiki_refs": wiki_refs})


def _has_0_7() -> bool:
    """memkernel 0.7's code is installed (its curation debt module), whatever the version string says."""
    import importlib.util

    return importlib.util.find_spec("memkernel.wiki.curation") is not None


def _snapshot(service: Any) -> list[tuple[Any, ...]]:
    return sorted(
        (m.ref_id, m.content, tuple(m.tags), m.supersedes, m.superseded_by, getattr(m, "withdrawn_reason", None))
        for m in service.list_memories(include_superseded=True)
    )


def _u_session_1(workdir: Path, checks: list[dict[str, Any]], values: dict[str, Any]) -> None:
    """On 0.7.x: the first import lists every 0.6 page as ambiguous and changes no memory."""
    from importlib import metadata

    version = metadata.version("memkernel")
    _check(checks, "memkernel-0.7-installed", _has_0_7(), version)  # main's wheel says 0.6.0 until the release
    service = _service()
    before = _snapshot(service)
    report = _import(service)
    pages = _values(workdir, "u-session-0")["pages"]
    reasons = sorted((a["path"], a["reason"]) for a in report.ambiguous)
    _check(
        checks,
        "every-page-ambiguous",
        reasons == sorted((rel, "legacy owner unproven") for rel in pages.values()),
        str(report.ambiguous),
    )
    _check(checks, "nothing-imported", report.imported == [], str(report.imported))
    _check(checks, "no-memory-changed", _snapshot(service) == before)
    values["version"] = version


def _u_session_2(workdir: Path, checks: list[dict[str, Any]], values: dict[str, Any]) -> None:
    """``adopt_legacy=true`` adopts each 0.6 record once."""
    service = _service()
    wiki_refs = _values(workdir, "u-session-0")["wiki_refs"]
    count = len(service.list_memories(include_superseded=True))
    report = _import(service, adopt_legacy=True)
    _check(checks, "nothing-ambiguous", report.ambiguous == [], str(report.ambiguous))
    adopted = [service.get(ref, touch=False) for ref in wiki_refs.values()]
    _check(
        checks,
        "records-adopted",
        all(m is not None and any(t.startswith("wiki-id:") for t in m.tags) for m in adopted),
    )
    _check(checks, "no-duplicate-record", len(service.list_memories(include_superseded=True)) == count)


def _u_curator(workdir: Path, checks: list[dict[str, Any]], values: dict[str, Any]) -> None:
    session_0 = _values(workdir, "u-session-0")
    rel = session_0["pages"]["wrong"]
    text = _read(rel).replace("status: stable", f"status: stable\ncorrects: {session_0['refs']['wrong']}", 1)
    lines = text.splitlines()
    _replace_one(lines, f"title: {TOPIC}", f"title: {RIGHT}", "correction-drafted")
    _replace_one(lines, f"# {TOPIC}", f"# {RIGHT}", "correction-drafted")
    _replace_one(lines, TOPIC, RIGHT, "correction-drafted")
    _replace_one(lines, WRONG, RIGHT, "correction-drafted")
    _propose_from(workdir, "u-curator", {rel: "\n".join(lines) + "\n"}, checks)
    _approve(workdir, [rel], checks, "u-curator")


def _u_session_3(workdir: Path, checks: list[dict[str, Any]], values: dict[str, Any]) -> None:
    """The adopted store runs the 0.7 loop: the correction, then a recall in a new process."""
    service = _service()
    session_0 = _values(workdir, "u-session-0")
    report = _import(service)
    _check(checks, "correction-recorded", [c["ref_id"] for c in report.corrections] == [session_0["refs"]["wrong"]])
    recalled = [service.get(r.ref_id, touch=False) for r in service.recall(QUESTION)]
    _check(checks, "right-answer-current", any(m is not None and RIGHT in m.content for m in recalled))
    _check(checks, "wrong-rule-not-current", not any(m is not None and WRONG in m.content for m in recalled))
    live = {session_0["pages"]["wrong"]: RIGHT, session_0["pages"]["other"]: UPGRADE_MEMORIES["other"][1]}
    files = {*session_0["pages"].values(), "index.md", "log.md"}
    values["summary"] = _converged(workdir, service, checks, live, {WRONG: "superseded"}, "upgrade", files)


STEPS = {
    "session-1": _session_1,
    "curator-1": _curator_1,
    "session-2-first": _session_2,
    "session-2-second": _session_2,
    "session-2-check": _session_2_check,
    "session-2-again": _session_2_again,
    "curator-2": _curator_2,
    "session-3-killed": _session_3_killed,
    "session-3": _session_3,
    "session-4": _session_4,
    "u-session-0": _u_session_0,
    "u-session-1": _u_session_1,
    "u-session-2": _u_session_2,
    "u-curator": _u_curator,
    "u-session-3": _u_session_3,
}


def _run_step(name: str, workdir: Path) -> int:
    """One step in this process: 0 passed, 1 a check failed, 2 cannot run."""
    os.chdir(workdir)
    checks: list[dict[str, Any]] = []
    values: dict[str, Any] = {}
    try:
        STEPS[name](workdir, checks, values)
    except CheckFailedError as exc:
        print(f"FAILED: {exc.name}{': ' + exc.detail if exc.detail else ''}", flush=True)
        _save(workdir, name, values, checks)
        return 1
    except CannotRunError as exc:
        print(f"cannot run: {exc}", flush=True)
        return 2
    except Exception:
        traceback.print_exc()
        checks.append({"name": f"{name}-raised", "ok": False, "detail": _tail(traceback.format_exc())})
        _save(workdir, name, values, checks)
        return 1
    _save(workdir, name, values, checks)
    return 0


# ── the orchestrator: never imports memkernel or wiki-studio ─────────────────


def _spawn(name: str, workdir: Path, governed: bool = True, **extra: str) -> subprocess.Popen[str]:
    env = {**_env(workdir, governed), **extra}
    return subprocess.Popen(  # noqa: S603
        [sys.executable, str(Path(__file__).resolve()), "step", name, "--workdir", str(workdir)],
        env=env,
        cwd=str(workdir),
        text=True,
    )


def _step(name: str, workdir: Path, governed: bool = True) -> int:
    print(f"== {name}", flush=True)
    return _spawn(name, workdir, governed).wait()


def _r4(workdir: Path) -> int:
    """Two imports at once: the first holds the lock until the second reached its import, then the hold."""
    print("== session-2 (R4: two imports)", flush=True)
    first = _spawn("session-2-first", workdir, EXIT_R4_ROLE="first")
    second = None
    try:
        _wait_for(workdir, "r4-first-wrote")
        second = _spawn("session-2-second", workdir, EXIT_R4_ROLE="second")
        _wait_for(workdir, "r4-second-reached")
        time.sleep(R4_HOLD_SECONDS)
        _mark(workdir, "r4-release")
    except CheckFailedError as exc:
        for process in (first, second):
            if process is not None:
                process.kill()
                process.wait()
        print(f"FAILED: {exc.name}: {exc.detail}", flush=True)
        return 1
    return max(first.wait(), second.wait())


def _main_run(workdir: Path) -> int:
    for name in ("session-1", "curator-1"):
        if code := _step(name, workdir):
            return code
    if code := _r4(workdir):
        return code
    for name in ("session-2-check", "session-2-again", "curator-2"):
        if code := _step(name, workdir):
            return code
    print("== session-3-killed (R2)", flush=True)
    killed = _spawn("session-3-killed", workdir).wait()  # os._exit(0) at the kill point
    if killed != 0 or not _marker(workdir, "r2-killed").exists():
        print(f"FAILED: r2-killed: the import never reached the predecessor's mark (exit {killed})", flush=True)
        return 1
    for name in ("session-3", "session-4"):
        if code := _step(name, workdir):
            return code
    return 0


def _upgrade_run(workdir: Path, upgrade_to: str) -> int:
    if code := _step("u-session-0", workdir, governed=False):
        return code
    print(f"== upgrade: pip install {upgrade_to}", flush=True)
    pip = subprocess.run(  # noqa: S603
        [sys.executable, "-m", "pip", "install", "--no-deps", "--force-reinstall", upgrade_to], text=True, check=False
    )
    if pip.returncode != 0:
        print("cannot run: the upgrade install failed", flush=True)
        return 2
    for name in UPGRADE_STEPS_07:
        if code := _step(name, workdir):
            return code
    return 0


def _summary(workdir: Path, code: int, path: Path | None) -> None:
    state = _load(workdir)
    checks = [check for step in state.values() for check in step.get("checks", [])]
    result = {"exit_code": code, "checks": checks, "steps": {k: v.get("values", {}) for k, v in state.items()}}
    if path is not None:
        path.write_text(json.dumps(result, indent=2, default=str) + "\n", encoding="utf-8")
    passed = sum(1 for check in checks if check["ok"])
    print(f"{'run: every check passed' if code == 0 else 'run: FAILED'} ({passed} of {len(checks)} checks passed)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command")
    step = sub.add_parser("step")
    step.add_argument("name", choices=sorted(STEPS))
    step.add_argument("--workdir", type=Path, required=True)
    parser.add_argument("--workdir", type=Path)
    parser.add_argument("--summary", type=Path)
    parser.add_argument("--upgrade", action="store_true", help="the upgrade run (E7)")
    parser.add_argument("--upgrade-to", help="what pip installs for 0.7.x in the upgrade run")
    args = parser.parse_args(argv)
    if args.command == "step":
        return _run_step(args.name, args.workdir.resolve())
    if args.workdir is None:
        parser.error("--workdir is required")
    workdir = args.workdir.resolve()
    if workdir.exists() and any(workdir.iterdir()):
        print(f"cannot run: --workdir {workdir} is not empty", flush=True)
        return 2
    if args.upgrade and not args.upgrade_to:
        parser.error("--upgrade needs --upgrade-to")
    workdir.mkdir(parents=True, exist_ok=True)
    try:
        _cli()
    except CannotRunError as exc:
        print(f"cannot run: {exc}", flush=True)
        return 2
    code = _upgrade_run(workdir, args.upgrade_to) if args.upgrade else _main_run(workdir)
    _summary(workdir, code, args.summary)
    return code


if __name__ == "__main__":
    sys.exit(main())

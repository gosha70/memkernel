#!/usr/bin/env python3
# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""Credential-free, ungraded wiring check of memkernel's wiki bridge (specs/memkernel-0-5 task 18a).

    wiring_check.py --suite <eval/lifecycle-suite> --memkernel-cmd <memkernel> [--shared-cache DIR]

Drives the real ``memkernel`` MCP server over stdio, with the environment the
lifecycle runner gives the memkernel arm, through the lc-wiki path. No model
and no agent are involved, and the fixture is synthetic, so no measured task
or outcome is touched. The steps:

1. source namespace: the store holds 0 records; ``retain`` a synthetic decision,
   then ``wiki_export``; the store then holds exactly 1 record;
2. transfer: the runner's own ``prepare_session`` builds the destination workspace
   under the memkernel arm's frozen rule; only ``knowledge/wiki/`` may differ
   from the fixture, and no fixture file may be missing (a ``NOTES.md`` written in the
   source workspace must not cross);
3. destination namespace: the store holds 0 records (counted through memkernel's
   library, not inferred from search) and ``recall`` finds nothing; ``wiki_import``;
   the store then holds exactly the imported pages; ``recall`` finds the page and
   ``get`` returns the synthetic sentence verbatim.

Import paths (``--wiki-path``, memkernel-0-7-wiring-spool W1, #81): ``governed`` marks the exported page stable
through a promoted update and approves it with wiki-studio, as a curator would, so the destination import is
governed; ``ungoverned`` hides wiki-studio from the server with a stub package that raises
``ModuleNotFoundError(name="wiki_studio")``, the only error memkernel treats as absence; ``both`` runs the two legs
in separate chains, each step prefixed with its leg; ``auto`` (the default) is ``governed`` when the server's
interpreter has wiki-studio 0.7.0 or later, else ``ungoverned``, so a run in the image without the ``wiki`` extra
keeps its 0.5 meaning.

Prints one JSON object with every step, exits 0 only when every step passes.
Inside the calibration image it runs with that image's own runner and
memkernel (``--suite /opt/memkernel/eval/lifecycle-suite``).
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

FIXTURE_DIR = Path(__file__).resolve().parent / "fixture"
FACT = "Wiring check fact: the synthetic billing service rounds invoice totals half-even to 4 decimal places."
QUERY = "synthetic billing service invoice rounding"
CHAIN_ID = "wiring-wiki-bridge.memkernel.r0"
NOTES = "NOTES.md"
INVENTORY = (
    "import json\n"
    "from memkernel.factory import build_service\n"
    "from memkernel.core.models import MemoryTier\n"
    "svc = build_service()\n"
    "print(json.dumps(sum(len(svc.list_memories(tier=t, include_superseded=True)) for t in MemoryTier)))\n"
)


WIKI_PATHS = ("auto", "governed", "ungoverned", "both")
GOVERNED, UNGOVERNED = "governed", "ungoverned"
STUB_MESSAGE = "wiki-studio hidden by the wiring check (ungoverned leg)"
CURATOR = "wiring-check"
# Run in the server's interpreter: the installed wiki-studio version, and memkernel's own floor check on it
# (memkernel.wiki.studio._below_floor: a pre-release of the floor, 0.7.0rc1, is below it).
STUDIO_STATUS = (
    "import importlib.metadata as m, json\n"
    "from memkernel.wiki.studio import _below_floor\n"
    "try:\n"
    "    import wiki_studio  # noqa: F401\n"
    "    version = m.version('wiki-studio')\n"
    "except ModuleNotFoundError:\n"
    "    version = ''\n"
    "print(json.dumps({'version': version, 'meets_floor': bool(version) and not _below_floor(version)}))\n"
)
CURATE = (
    "import sys\n"
    "from pathlib import Path\n"
    "from wiki_studio import api\n"
    "from wiki_studio.paths import WikiPaths\n"
    "from wiki_studio.proposal import PageEdit\n"
    "root, rel = Path(sys.argv[1]), sys.argv[2]\n"
    "paths = WikiPaths.for_root(root, wiki_dir=root / sys.argv[3], proposals_dir=Path(sys.argv[4]))\n"
    "page = api.read_page(rel, paths)\n"
    "edit = PageEdit(rel, 'update', page.text.replace('status: draft', 'status: stable', 1), 'curated', page.sha256)\n"
    "api.promote(api.propose([edit], paths, name='wiring-curate'), paths, by=sys.argv[5])\n"
    "api.approve([rel], paths, by=sys.argv[5])\n"
    "print('approved')\n"
)


def write_stub(directory: Path) -> Path:
    """A ``wiki_studio`` package whose import raises ``ModuleNotFoundError(name="wiki_studio")``; return the
    directory to put first on ``PYTHONPATH``."""
    package = directory / "wiki_studio"
    package.mkdir(parents=True, exist_ok=True)
    (package / "__init__.py").write_text(
        f"raise ModuleNotFoundError({STUB_MESSAGE!r}, name='wiki_studio')\n", encoding="utf-8"
    )
    return directory


def studio_status(python: str) -> dict[str, Any]:
    """``{"version", "meets_floor"}`` for the server's interpreter: its wiki-studio version ("" without one) and
    whether memkernel's own floor check accepts it; both empty or false when the probe itself fails."""
    completed = subprocess.run(
        [python, "-c", STUDIO_STATUS], env=_server_env({}), capture_output=True, text=True, timeout=120, check=False
    )
    lines = completed.stdout.strip().splitlines()
    if completed.returncode != 0 or not lines:
        return {"version": "", "meets_floor": False}
    status: dict[str, Any] = json.loads(lines[-1])
    return status


def resolve_wiki_path(wiki_path: str, python: str) -> list[str]:
    """The legs to run: ``auto`` is governed when memkernel's floor check accepts the installed wiki-studio."""
    if wiki_path == "both":
        return [GOVERNED, UNGOVERNED]
    if wiki_path != "auto":
        return [wiki_path]
    return [GOVERNED if studio_status(python)["meets_floor"] else UNGOVERNED]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _files(root: Path) -> set[str]:
    return {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}


def transfer_findings(fixture_tree: Path, destination: Path, wiki_dir: str) -> dict[str, Any]:
    """What crossed into the destination workspace, judged against the fixture alone (no server, no image).

    ``only_wiki_crossed`` holds when something crossed and everything that crossed lies under ``wiki_dir``
    (so the source workspace's ``NOTES.md`` must not); ``missing`` lists fixture files absent from the
    destination; ``changed_outside_wiki`` lists fixture files outside the wiki whose bytes differ.

    It does not judge what lies under ``wiki_dir``: the memkernel arm's frozen rule carries that directory over
    whole, by design, so a stray file written there would cross and still pass.
    """
    fixture_files = _files(fixture_tree)
    destination_files = _files(destination)
    crossed = sorted(destination_files - fixture_files)
    missing = sorted(fixture_files - destination_files)
    wiki_prefix = wiki_dir + "/"
    changed_outside_wiki = sorted(
        rel
        for rel in fixture_files & destination_files
        if not rel.startswith(wiki_prefix) and (destination / rel).read_bytes() != (fixture_tree / rel).read_bytes()
    )
    only_wiki = bool(crossed) and all(p.startswith(wiki_prefix) for p in crossed)
    return {
        "crossed": crossed,
        "only_wiki_crossed": only_wiki,
        "missing": missing,
        "changed_outside_wiki": changed_outside_wiki,
    }


def _server_env(namespace_env: dict[str, str]) -> dict[str, str]:
    """What Claude Code gives the server: a minimal base (no credentials) plus the arm's MCP env."""
    base = {key: os.environ[key] for key in ("PATH", "LANG", "LC_ALL", "TMPDIR") if key in os.environ}
    return {**base, **namespace_env}


def _inventory(python: str, namespace_env: dict[str, str]) -> int:
    """Records in a namespace's store, counted by memkernel itself while no server holds the store."""
    completed = subprocess.run(
        [python, "-c", INVENTORY],
        env=_server_env(namespace_env),
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"inventory failed: {completed.stderr.strip()[-500:]}")
    return int(completed.stdout.strip().splitlines()[-1])


async def _call(
    memkernel_cmd: str, namespace_env: dict[str, str], calls: list[tuple[str, dict[str, Any]]]
) -> list[Any]:
    """Start the memkernel server over stdio, make ``calls`` in order, return their parsed JSON results."""
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    params = StdioServerParameters(command=memkernel_cmd, args=[], env=_server_env(namespace_env))
    results = []
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        for name, arguments in calls:
            result = await session.call_tool(name, arguments=arguments)
            text = "".join(getattr(block, "text", "") for block in result.content)
            if result.isError:
                raise RuntimeError(f"{name} returned an error: {text[:500]}")
            results.append(json.loads(text))
    return results


def run_check(
    suite: Path, memkernel_cmd: str, python: str, shared_cache: Path | None, wiki_path: str = "auto"
) -> dict[str, Any]:
    sys.path.insert(0, str(suite))
    import runner  # type: ignore[import-not-found]  # the suite's own runner: the same prepare_session and MCP environment as a real run

    legs = resolve_wiki_path(wiki_path, python)
    steps: list[dict[str, Any]] = []
    report: dict[str, Any] = {
        "check": "wiki-bridge wiring (task 18a)",
        "check_sha256": _sha256(Path(__file__)),
        "fixture_sha256": {p: _sha256(FIXTURE_DIR / p) for p in sorted(_files(FIXTURE_DIR))},
        "suite": str(suite),
        "code_sha": os.environ.get("CODE_SHA", "unknown"),
        "wiki_path": wiki_path,
        "legs": legs,
        "steps": steps,
    }
    for leg in legs:
        prefix = f"{leg}: " if len(legs) > 1 else ""
        _run_leg(runner, leg, prefix, steps, report, memkernel_cmd, python, shared_cache)
    report["passed"] = all(s["passed"] for s in steps)
    return report


def _run_leg(
    runner: Any,
    leg: str,
    prefix: str,
    steps: list[dict[str, Any]],
    report: dict[str, Any],
    memkernel_cmd: str,
    python: str,
    shared_cache: Path | None,
) -> None:
    """One import path, in its own chain: source namespace, transfer, destination namespace."""

    def step(name: str, passed: bool, **detail: Any) -> bool:
        steps.append({"step": f"{prefix}{name}", "passed": passed, **detail})
        return passed

    with tempfile.TemporaryDirectory(prefix="wiring-") as tmp:
        work = Path(tmp)
        task = runner.load_task(FIXTURE_DIR)
        arm = runner.load_arm("memkernel")
        cfg = runner.RunConfig(
            run_root=work,
            run_id="wiring",
            phase="wiring",
            model="none",
            code_sha=report["code_sha"],
            preregistration_sha256=None,
            agent_cmd=("none",),
            memkernel_cmd=memkernel_cmd,
            memkernel_python=python,
            tasks_root=FIXTURE_DIR.parent,
            oracles_root=work,
            shared_cache=shared_cache,
        )
        chain = work / CHAIN_ID
        chain.mkdir()

        # 1. source namespace
        source = runner.prepare_session(task, arm, 0, chain, runner.ChainState())
        hidden = {"PYTHONPATH": str(write_stub(work / "hide-wiki-studio"))} if leg == UNGOVERNED else {}
        if leg == GOVERNED:
            status = studio_status(python)
            if not step(
                "the server's interpreter has wiki-studio at memkernel's floor (governed leg)",
                bool(status["meets_floor"]),
                version=status["version"],
            ):
                return
        source_env = {**runner._memkernel_env(source, CHAIN_ID, cfg), **hidden}
        step("source store starts empty", _inventory(python, source_env) == 0)
        retained, exported = asyncio.run(
            _call(memkernel_cmd, source_env, [("retain", {"content": FACT, "type": "decision"}), ("wiki_export", {})])
        )
        written = exported.get("written", [])
        step("retain returned a ref_id", bool(retained.get("ref_id")), ref_id=retained.get("ref_id"))
        step(
            "wiki_export wrote exactly one page",
            len(written) == 1,
            written=written,
            gate_error=exported.get("gate_error"),
        )
        step("source store holds exactly 1 record", _inventory(python, source_env) == 1)
        if leg == GOVERNED and len(written) == 1:  # as a curator would: stable, then approved
            curated = subprocess.run(
                [
                    python,
                    "-c",
                    CURATE,
                    str(source.workspace),
                    written[0],
                    runner.WIKI_DIR,
                    str(source.workspace / ".memkernel" / "wiki-proposals"),  # inside the root; never crosses
                    CURATOR,
                ],
                env=_server_env(source_env),
                capture_output=True,
                text=True,
                timeout=300,
                check=False,
            )
            step(
                "the exported page was marked stable and approved",
                curated.returncode == 0 and curated.stdout.strip().endswith("approved"),
                error=curated.stderr.strip()[-500:] or None,
            )
        (source.workspace / NOTES).write_text("written in the source workspace; must not cross\n", encoding="utf-8")

        # 2. transfer, by the runner's own code and the arm's frozen rule
        destination = runner.prepare_session(
            task, arm, 1, chain, runner.ChainState(workspace=source.workspace, transcripts=[])
        )
        findings = transfer_findings(task.tree, destination.workspace, runner.WIKI_DIR)
        step("every fixture file is in the destination", not findings["missing"], missing=findings["missing"])
        step(
            "fixture files outside knowledge/wiki/ are byte-identical",
            not findings["changed_outside_wiki"],
            changed=findings["changed_outside_wiki"],
        )
        step("only knowledge/wiki/ crossed over", findings["only_wiki_crossed"], crossed=findings["crossed"])
        step(
            "the exported page crossed over",
            all((destination.workspace / runner.WIKI_DIR / page).is_file() for page in written),
        )
        step(
            "destination is a second namespace", destination.namespace == "second" and destination.store != source.store
        )

        # 3. destination namespace
        destination_env = {**runner._memkernel_env(destination, CHAIN_ID, cfg), **hidden}
        step("destination store starts with 0 records", _inventory(python, destination_env) == 0)
        before, imported, after = asyncio.run(
            _call(
                memkernel_cmd,
                destination_env,
                [
                    ("recall", {"query": QUERY, "top_k": 5}),
                    ("wiki_import", {}),
                    ("recall", {"query": QUERY, "top_k": 5}),
                ],
            )
        )
        step("recall finds nothing before import", before == [], hits=len(before))
        imported_pages = imported.get("imported", [])
        step(
            "wiki_import imported the exported page", sorted(imported_pages) == sorted(written), imported=imported_pages
        )
        step(f"wiki_import was {leg}", imported.get("governed") is (leg == GOVERNED), governed=imported.get("governed"))
        step(
            "destination store holds exactly the imported pages",
            _inventory(python, destination_env) == len(imported_pages),
        )
        ref_id = after[0]["ref_id"] if after else None
        (memory,) = (
            asyncio.run(_call(memkernel_cmd, destination_env, [("get", {"ref_id": ref_id})])) if ref_id else ({},)
        )
        step(
            "get returns the synthetic sentence verbatim",
            FACT in str(memory.get("content", "")) and "wiki" in memory.get("tags", []),
            ref_id=ref_id,
            source=memory.get("source"),
        )


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--suite", type=Path, default=Path("/opt/memkernel/eval/lifecycle-suite"))
    parser.add_argument("--memkernel-cmd", default="/opt/mk-venv/bin/memkernel")
    parser.add_argument("--python", default=sys.executable, help="interpreter with memkernel installed (inventory)")
    parser.add_argument("--shared-cache", type=Path, help="as the runner's --shared-cache (HF_HOME for the server)")
    parser.add_argument("--wiki-path", choices=WIKI_PATHS, default="auto", help="import path(s) to check (#81)")
    args = parser.parse_args(argv)
    try:
        report = run_check(args.suite.resolve(), args.memkernel_cmd, args.python, args.shared_cache, args.wiki_path)
    except Exception as exc:  # any failure to run the check is a failed check, reported, never a pass
        report = {"check": "wiki-bridge wiring (task 18a)", "passed": False, "error": f"{type(exc).__name__}: {exc}"}
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

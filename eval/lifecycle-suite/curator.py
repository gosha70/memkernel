# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""The composition arms' curators (specs/memkernel-0-16-lifecycle-corrections FR-004, D3; #90 section 3.3).

``scripted`` follows the frozen policy in ``arms/memkernel_governed/curator-policy.md`` (hashed with that arm): it
uses only the drafts memkernel exported and the task's correction brief, never the task id. ``oracle`` is the upper
bound beside it: it lands the corrected rule through the gate whatever the session left, and names every live
memory carrying the obsolete rule in ``corrects``. Both act only through wiki-studio's command line (``read --json``,
``propose --from ... --promote --by curator``, ``approve --by curator``), so every page they land has the gate's
receipt and approval records.

Stdlib only: memkernel is reached through ``ops`` (``memkernel_ops.py`` in the chain's environment) and wiki-studio
through ``cli``; the runner supplies both.
"""

from __future__ import annotations

import json
import re
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

SCRIPTED, ORACLE = "scripted", "oracle"
CURATOR = "curator"
WIKI_DIR = Path("knowledge") / "wiki"
REF_KEY = "memkernel_ref"
CORRECTS_KEY = "corrects"
DRAFT, STABLE = "draft", "stable"
FILLER = "Corrected by the curator from the team's correction brief; see the first section."
ORACLE_DIR = "decisions"
ORACLE_TYPE = "decision"
ORACLE_SECTIONS = ("Decision", "Context", "Alternatives considered", "Consequences")

Ops = Callable[..., dict[str, Any]]  # ops("exists", ref) -> parsed JSON
Cli = Callable[..., tuple[int, str]]  # cli("read", "--json", rel) -> (exit code, stdout)


def split_page(text: str) -> tuple[list[str], str]:
    """(frontmatter lines, body) of a page; no frontmatter gives ([], text)."""
    if not text.startswith("---\n"):
        return [], text
    end = text.find("\n---\n", 4)
    if end < 0:
        return [], text
    return text[4:end].split("\n"), text[end + 5 :]


def scalar(lines: list[str], key: str) -> str | None:
    for line in lines:
        if line.startswith(f"{key}:"):
            return line.split(":", 1)[1].strip().strip("'\"")
    return None


def _set(lines: list[str], key: str, value: str) -> list[str]:
    out = [line for line in lines if not line.startswith(f"{key}:")]
    position = next((i for i, line in enumerate(out) if line.startswith("last_reviewed:")), len(out))
    return [*out[:position], f"{key}: {value}", *out[position:]]


def corrected(text: str, brief: dict[str, Any], corrects: list[str]) -> str:
    """The policy's page: title and heading from the brief's headline, the first section the brief's rule, the other
    sections' text replaced by a fixed line; ``status: stable`` and ``corrects``; every other key kept."""
    lines, body = split_page(text)
    headline = str(brief["headline"])
    lines = [line for line in lines if not line.startswith(("title:", "status:"))]
    lines = _set(_set(_set(lines, "title", json.dumps(headline)), "status", STABLE), CORRECTS_KEY, ", ".join(corrects))
    sections = re.findall(r"^## (.+)$", body, flags=re.MULTILINE)
    out = [f"# {headline}", ""]
    for index, heading in enumerate(sections or ["Decision"]):
        out += [f"## {heading}", "", str(brief["rule"]) if index == 0 else FILLER, ""]
    return "---\n" + "\n".join(lines) + "\n---\n" + "\n".join(out)


def drafts(workspace: Path) -> list[tuple[str, str, str]]:
    """(wiki path, text, memkernel_ref) of every draft memkernel exported into the wiki."""
    wiki = workspace / WIKI_DIR
    found = []
    for page in sorted(wiki.rglob("*.md")):
        rel = page.relative_to(wiki)
        if any(part.startswith(".") for part in rel.parts):
            continue
        text = page.read_text(encoding="utf-8")
        lines, _ = split_page(text)
        ref = scalar(lines, REF_KEY)
        if ref and scalar(lines, "status") == DRAFT:
            found.append((rel.as_posix(), text, ref))
    return found


class CuratorError(RuntimeError):
    """wiki-studio or the memkernel helper answered with something the curator cannot read: a harness failure."""


def read_page(cli: Cli, rel: str) -> tuple[str, str] | None:
    """(content, sha256) from ``read --json``, or None when wiki-studio refuses the read."""
    code, out = cli("read", "--json", rel)
    if code != 0:
        return None
    try:
        parsed = json.loads(out)
        return str(parsed["content"]), str(parsed["sha256"])
    except (ValueError, KeyError, TypeError) as exc:
        raise CuratorError(f"wiki-studio read --json {rel} printed no page: {exc}") from exc


def _land(
    cli: Cli,
    rel: str,
    render: Callable[[str], str],
    read: tuple[str, str] | None,
    name: str,
    index_line: str | None = None,
) -> str | None:
    """Propose and promote one page, then approve it; None on success, else the refusal.

    An update starts from ``read`` (content, sha256) and is guarded by its sha256; ``render`` turns the page's
    content into the corrected page. A refused propose is retried once from a fresh ``read``, re-rendered from that
    read, so a concurrent change is corrected rather than overwritten (the policy's stale-base retry). A create
    (``read`` None) renders from nothing and is not retried.
    """
    for attempt in (1, 2):
        text = render(read[0] if read is not None else "")
        with tempfile.TemporaryDirectory() as tmp:
            draft = Path(tmp) / "draft"
            target = draft / rel
            target.parent.mkdir(parents=True)
            target.write_text(text, encoding="utf-8")
            if read is not None:
                (draft / ".base.json").write_text(json.dumps({rel: read[1]}), encoding="utf-8")
            if index_line is not None:
                (draft / "index.md").write_text(index_line + "\n", encoding="utf-8")
            code, out = cli(
                "propose", "--from", str(draft), "--promote", "--by", CURATOR, "--name", f"{name}-{attempt}"
            )
        if code == 0:
            break
        if read is None or attempt == 2:
            return f"propose refused (exit {code}): {out.strip()[:300]}"
        read = read_page(cli, rel)
        if read is None:
            return "read failed before the retry"
    code, out = cli("approve", rel, "--by", CURATOR)
    return None if code == 0 else f"approve refused (exit {code}): {out.strip()[:300]}"


def curate(mode: str, brief: dict[str, Any], workspace: Path, ops: Ops, cli: Cli) -> dict[str, Any]:
    patterns = [re.compile(p, re.IGNORECASE) for p in brief["obsolete_patterns"]]
    candidates = [d for d in drafts(workspace) if any(p.search(d[1]) for p in patterns)]
    landed: list[str] = []
    refusals: list[dict[str, str]] = []
    extra: list[str] = []
    if mode == ORACLE:
        extra = [str(ref) for ref in ops("find", "--patterns", json.dumps(brief["obsolete_patterns"]))["ref_ids"]]
    for number, (rel, _text, ref) in enumerate(candidates, start=1):
        if not ops("exists", ref)["live"]:
            refusals.append({"page": rel, "reason": f"corrects target {ref} is not a live memory"})
            continue
        read = read_page(cli, rel)
        if read is None:
            refusals.append({"page": rel, "reason": "read failed"})
            continue
        names = list(dict.fromkeys([ref, *extra]))

        def render(content: str, names: list[str] = names) -> str:
            return corrected(content, brief, names)

        refusal = _land(cli, rel, render, read, f"curator-{number}")
        if refusal is None:
            landed.append(rel)
        else:
            refusals.append({"page": rel, "reason": refusal})
    if not candidates and mode == SCRIPTED:
        refusals.append({"page": "", "reason": "no exported draft carries the obsolete rule"})
    if mode == ORACLE and not landed:
        rel = oracle_page_path(brief, workspace)
        text = oracle_page(brief, extra, Path(rel).stem)
        index_line = f"- [{brief['headline']}]({rel}) — the current rule."
        refusal = _land(cli, rel, lambda _: text, None, "curator-oracle", index_line)
        if refusal is None:
            landed.append(rel)
        else:
            refusals.append({"page": rel, "reason": refusal})
    return {"mode": mode, "landed": landed, "refusals": refusals, "delivered": bool(landed)}


def oracle_page_path(brief: dict[str, Any], workspace: Path) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", str(brief["headline"]).lower()).strip("-")[:60].strip("-")
    rel = f"{ORACLE_DIR}/{slug}.md"
    suffix = 2
    while (workspace / WIKI_DIR / rel).exists():
        rel = f"{ORACLE_DIR}/{slug}-{suffix}.md"
        suffix += 1
    return rel


def oracle_page(brief: dict[str, Any], corrects: list[str], slug: str) -> str:
    lines = [
        f"page_type: {ORACLE_TYPE}",
        f"slug: {slug}",
        f"title: {json.dumps(str(brief['headline']))}",
        f"status: {STABLE}",
        *([f"{CORRECTS_KEY}: {', '.join(corrects)}"] if corrects else []),
        "last_reviewed: 2026-11-25",
        "sources:",
        "  - path: README.md",
    ]
    body = [f"# {brief['headline']}", ""]
    for index, heading in enumerate(ORACLE_SECTIONS):
        body += [f"## {heading}", "", str(brief["rule"]) if index == 0 else FILLER, ""]
    return "---\n" + "\n".join(lines) + "\n---\n" + "\n".join(body)

# Copyright (c) EGOGE - All Rights Reserved.
# This software may be used and distributed according to the terms of the MIT license.
"""Wiki page model plus a dependency-free frontmatter parser/renderer.

The page format follows the schema used by ``code-copilot-team/knowledge/wiki``
(page_type, slug, title, status, last_reviewed, sources) so that pages compiled
by MemKernel pass that wiki's structural linter unchanged.

Only the YAML subset those pages use is supported: top-level scalars and a
``sources:`` list whose items are flat ``key: value`` mappings.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field

_FRONTMATTER_RE = re.compile(r"\A---[ \t]*\n(.*?)\n---[ \t]*\n?", re.DOTALL)
_SLUG_RE = re.compile(r"[^a-z0-9]+")


class WikiPage(BaseModel):
    """A single markdown page with its frontmatter."""

    page_type: str
    slug: str
    title: str
    status: str = "draft"
    last_reviewed: str = ""
    sources: list[dict[str, str]] = Field(default_factory=list)
    body: str = ""
    extra: dict[str, str] = Field(default_factory=dict)


def slugify(text: str, max_len: int = 60) -> str:
    """Return a kebab-case slug suitable for a wiki filename."""
    slug = _SLUG_RE.sub("-", text.lower()).strip("-")
    if len(slug) > max_len:
        slug = slug[:max_len].rstrip("-")
    return slug or "untitled"


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def _parse_frontmatter(block: str) -> tuple[dict[str, str], list[dict[str, str]]]:
    """Parse the supported YAML subset into (scalars, sources)."""
    scalars: dict[str, str] = {}
    sources: list[dict[str, str]] = []
    in_sources = False
    current: dict[str, str] | None = None
    for raw in block.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indented = raw[0] in " \t"
        line = raw.strip()
        if not indented:
            in_sources = False
            current = None
            key, sep, value = line.partition(":")
            if not sep:
                continue
            key = key.strip()
            if key == "sources":
                in_sources = True
                continue
            scalars[key] = _unquote(value)
            continue
        if not in_sources:
            continue
        if line.startswith("- "):
            current = {}
            sources.append(current)
            line = line[2:].strip()
        if current is None:
            continue
        key, sep, value = line.partition(":")
        if sep:
            current[key.strip()] = _unquote(value)
    return scalars, sources


def parse_page(text: str) -> WikiPage | None:
    """Parse a markdown document with YAML frontmatter. Returns None if it has none."""
    match = _FRONTMATTER_RE.match(text)
    if match is None:
        return None
    scalars, sources = _parse_frontmatter(match.group(1))
    body = text[match.end() :]
    known = {"page_type", "slug", "title", "status", "last_reviewed"}
    page_type = scalars.get("page_type", "")
    slug = scalars.get("slug", "")
    if not page_type or not slug:
        return None
    return WikiPage(
        page_type=page_type,
        slug=slug,
        title=scalars.get("title", slug),
        status=scalars.get("status", "draft"),
        last_reviewed=scalars.get("last_reviewed", ""),
        sources=sources,
        body=body.strip("\n") + "\n" if body.strip() else "",
        extra={k: v for k, v in scalars.items() if k not in known},
    )


def _quote(value: str) -> str:
    """Quote a scalar when YAML would otherwise misread it."""
    if value == "" or any(ch in value for ch in ":#\"'[]{}") or value != value.strip():
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return value


def render_page(page: WikiPage) -> str:
    """Render a WikiPage back to markdown with frontmatter."""
    lines = [
        "---",
        f"page_type: {page.page_type}",
        f"slug: {page.slug}",
        f"title: {_quote(page.title)}",
        f"status: {page.status}",
        f"last_reviewed: {page.last_reviewed}",
    ]
    for key, value in page.extra.items():
        lines.append(f"{key}: {_quote(value)}")
    if page.sources:
        lines.append("sources:")
        for source in page.sources:
            first = True
            for key, value in source.items():
                prefix = "  - " if first else "    "
                lines.append(f"{prefix}{key}: {_quote(value)}")
                first = False
    lines.append("---")
    lines.append("")
    return "\n".join(lines) + page.body


def body_sections(body: str) -> dict[str, str]:
    """Split a page body into its ``##`` sections (heading -> text)."""
    sections: dict[str, str] = {}
    current: str | None = None
    buffer: list[str] = []
    for line in body.splitlines():
        if line.startswith("## "):
            if current is not None:
                sections[current] = "\n".join(buffer).strip()
            current = line[3:].strip()
            buffer = []
        elif current is not None:
            buffer.append(line)
    if current is not None:
        sections[current] = "\n".join(buffer).strip()
    return sections


def page_to_dict(page: WikiPage) -> dict[str, Any]:
    """JSON-friendly view of a page (used by the MCP tools)."""
    return page.model_dump()

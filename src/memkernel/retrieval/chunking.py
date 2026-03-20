# Copyright (c) EGOGE - All Rights Reserved.
# This software may be used and distributed according to the terms of the MIT license.
"""AST-aware code chunker implementing ChunkerPort.

Splits code files at syntactic boundaries (functions, classes, methods) using
tree-sitter.  Falls back to a sliding-window token chunker for unsupported
languages or when tree-sitter is unavailable.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from memkernel.config import MemKernelSettings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Language configuration
# ---------------------------------------------------------------------------

# Maps normalised language name -> tree-sitter language module import path.
# MVP: Python only.  Add tree-sitter-javascript / tree-sitter-typescript deps
# and extend this dict when JS/TS support is needed.
_LANG_MODULE: dict[str, str] = {
    "python": "tree_sitter_python",
}

# Boundary node types per language — AST node kinds at whose boundaries we
# split.  Nodes within chunk_size are emitted as chunks; oversized nodes are
# recursed into to find inner boundaries.
_BOUNDARY_NODES: dict[str, frozenset[str]] = {
    "python": frozenset({"function_definition", "class_definition", "decorated_definition"}),
}

# Maps file extensions to normalised language names.
# Only extensions with a corresponding entry in _LANG_MODULE produce AST chunks.
_EXT_TO_LANG: dict[str, str] = {
    ".py": "python",
}


# ---------------------------------------------------------------------------
# Token-based fallback (pure function, no tree-sitter dependency)
# ---------------------------------------------------------------------------


def _token_chunks(text: str, chunk_size: int, chunk_overlap: int) -> list[str]:
    """Sliding-window character chunker.

    Returns ``[text]`` when ``len(text) <= chunk_size``.
    Returns ``[]`` for empty input.
    Each chunk is at most ``chunk_size`` characters.
    Consecutive chunks share ``chunk_overlap`` characters at their boundary.
    """
    if not text:
        return []
    if len(text) <= chunk_size:
        return [text]

    chunks: list[str] = []
    step = max(1, chunk_size - chunk_overlap)
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        start += step
    return chunks


# ---------------------------------------------------------------------------
# ASTChunker
# ---------------------------------------------------------------------------


class ASTChunker:
    """Chunk code files at AST syntactic boundaries with a token fallback.

    Implements ``ChunkerPort``.
    Language is auto-detected from ``metadata["source"]`` file extension.
    """

    def __init__(self, settings: MemKernelSettings) -> None:
        self._settings = settings
        # Lazy cache: language name -> tree-sitter Parser | None
        self._parsers: dict[str, Any] = {}

    # ------------------------------------------------------------------
    # ChunkerPort
    # ------------------------------------------------------------------

    def chunk(self, content: str, metadata: dict[str, Any]) -> list[str]:
        """Return a list of chunk strings for *content*.

        Uses AST chunking when the source language is supported and
        tree-sitter is available; otherwise falls back to token chunking.
        """
        if not content:
            return []

        source: str = metadata.get("source", "")
        ext = Path(source).suffix.lower()
        language = _EXT_TO_LANG.get(ext)

        if language is None:
            logger.debug("Unknown extension %r — using token chunker", ext)
            return _token_chunks(content, self._settings.chunk_size, self._settings.chunk_overlap)

        ast_result = self._ast_chunks(content, language)
        if ast_result is not None:
            return ast_result

        logger.debug("AST chunking produced no splits for %r — using token chunker", source)
        return _token_chunks(content, self._settings.chunk_size, self._settings.chunk_overlap)

    # ------------------------------------------------------------------
    # AST chunking internals
    # ------------------------------------------------------------------

    def _ast_chunks(self, content: str, language: str) -> list[str] | None:
        """Attempt AST-based chunking.  Returns None to signal fallback."""
        parser = self._load_parser(language)
        if parser is None:
            return None

        encoded = content.encode("utf-8")
        try:
            tree = parser.parse(encoded)
        except Exception:
            logger.debug("tree-sitter parse failed — falling back to token chunker", exc_info=True)
            return None

        boundary_types = _BOUNDARY_NODES.get(language, frozenset())
        chunks: list[str] = []
        self._walk(tree.root_node, encoded, boundary_types, chunks)

        if not chunks:
            return None
        return chunks

    def _walk(
        self,
        node: Any,
        encoded: bytes,
        boundary_types: frozenset[str],
        chunks: list[str],
    ) -> None:
        """Depth-first walk; emit boundary nodes as chunks or recurse into them.

        Uses the original UTF-8 byte sequence for slicing so that byte offsets
        from tree-sitter nodes are always correct, even for non-ASCII source.
        """
        if node.type in boundary_types:
            text = encoded[node.start_byte : node.end_byte].decode("utf-8")
            if len(text) <= self._settings.chunk_size:
                if text.strip():
                    chunks.append(text)
                return
            # Oversized boundary node — recurse to find inner boundaries
            for child in node.children:
                self._walk(child, encoded, boundary_types, chunks)
            return

        for child in node.children:
            self._walk(child, encoded, boundary_types, chunks)

    # ------------------------------------------------------------------
    # Parser loader
    # ------------------------------------------------------------------

    def _load_parser(self, language: str) -> Any | None:
        """Lazy-load and cache a tree-sitter Parser for *language*.

        Returns None on any import/init error so the caller can fall back
        gracefully.
        """
        if language in self._parsers:
            return self._parsers[language]

        parser: Any | None = None
        try:
            import importlib

            import tree_sitter

            module_name = _LANG_MODULE[language]
            lang_module = importlib.import_module(module_name)

            # tree-sitter-python (and siblings) expose a ``language()``
            # function that returns a Language object.
            lang_obj = tree_sitter.Language(lang_module.language())
            p = tree_sitter.Parser(lang_obj)
            parser = p
            logger.debug("Loaded tree-sitter parser for %r", language)
        except (ImportError, OSError, ValueError, Exception):
            logger.debug(
                "Could not load tree-sitter parser for %r — will use token chunker",
                language,
                exc_info=True,
            )
            parser = None

        self._parsers[language] = parser
        return parser

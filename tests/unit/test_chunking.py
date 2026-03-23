"""Unit tests for ASTChunker and the _token_chunks fallback."""

from __future__ import annotations

from typing import Any

import pytest

from memkernel.config import MemKernelSettings
from memkernel.retrieval.chunking import ASTChunker, _token_chunks

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_settings(**overrides: Any) -> MemKernelSettings:
    base: dict[str, Any] = {
        "project_id": "test-chunk-default",
        "chunk_size": 100,
        "chunk_overlap": 20,
    }
    base.update(overrides)
    return MemKernelSettings(**base)


# ---------------------------------------------------------------------------
# _token_chunks unit tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_token_chunks_short_text_returns_single_chunk() -> None:
    """Text at or below chunk_size is returned as a single-element list."""
    text = "short text"
    result = _token_chunks(text, chunk_size=100, chunk_overlap=10)
    assert result == [text]


@pytest.mark.unit
def test_token_chunks_long_text_splits() -> None:
    """Text longer than chunk_size produces multiple chunks, each <= chunk_size."""
    text = "x" * 250
    result = _token_chunks(text, chunk_size=100, chunk_overlap=20)
    assert len(result) > 1
    for chunk in result:
        assert len(chunk) <= 100


@pytest.mark.unit
def test_token_chunks_overlap() -> None:
    """Consecutive chunks share chunk_overlap characters at their boundary."""
    chunk_size = 50
    chunk_overlap = 10
    text = "abcdefghij" * 10  # 100 chars
    result = _token_chunks(text, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    assert len(result) >= 2
    # The tail of result[0] and the head of result[1] must share chunk_overlap chars
    assert result[0][-chunk_overlap:] == result[1][:chunk_overlap]


@pytest.mark.unit
def test_token_chunks_empty_returns_empty() -> None:
    """Empty string input produces an empty list."""
    assert _token_chunks("", chunk_size=100, chunk_overlap=20) == []


# ---------------------------------------------------------------------------
# ASTChunker — fallback and edge cases
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_ast_chunker_empty_content_returns_empty() -> None:
    """chunk('', {}) must return []."""
    chunker = ASTChunker(_make_settings())
    assert chunker.chunk("", {}) == []


@pytest.mark.unit
def test_ast_chunker_no_source_falls_back_to_token() -> None:
    """Metadata without 'source' falls back to token chunking."""
    long_text = "word " * 100  # well over default chunk_size of 100
    chunker = ASTChunker(_make_settings())
    result = chunker.chunk(long_text, {})
    # Token fallback must produce at least one chunk and each <= chunk_size
    assert len(result) >= 1
    for chunk in result:
        assert len(chunk) <= chunker._settings.chunk_size


@pytest.mark.unit
def test_ast_chunker_unknown_extension_falls_back_to_token() -> None:
    """Unsupported extension (.md) falls back to token chunking."""
    long_text = "# heading\n" * 50
    chunker = ASTChunker(_make_settings())
    result = chunker.chunk(long_text, {"source": "README.md"})
    assert len(result) >= 1
    for chunk in result:
        assert len(chunk) <= chunker._settings.chunk_size


# ---------------------------------------------------------------------------
# ASTChunker — Python AST chunking (requires tree-sitter-python)
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_ast_chunker_python_splits_at_functions() -> None:
    """Two top-level Python functions → two AST chunks."""
    code = """\
def foo():
    return 1


def bar():
    return 2
"""
    # Use a chunk_size large enough that neither function is oversized
    chunker = ASTChunker(_make_settings(chunk_size=1500, chunk_overlap=200))
    result = chunker.chunk(code, {"source": "module.py"})
    assert len(result) == 2
    assert any("def foo" in c for c in result)
    assert any("def bar" in c for c in result)


@pytest.mark.slow
def test_ast_chunker_python_short_class_is_single_chunk() -> None:
    """A small Python class fits within chunk_size → emitted as one chunk."""
    code = """\
class MyClass:
    x: int = 0

    def method(self) -> int:
        return self.x
"""
    chunker = ASTChunker(_make_settings(chunk_size=1500, chunk_overlap=200))
    result = chunker.chunk(code, {"source": "myclass.py"})
    # The whole class fits in one chunk
    assert len(result) == 1
    assert "class MyClass" in result[0]


@pytest.mark.slow
def test_ast_chunker_oversized_class_recurses_into_methods() -> None:
    """A class larger than chunk_size is not emitted as one chunk.

    _walk must recurse into the oversized class_definition node and emit each
    method (function_definition child) as a separate chunk.  This exercises
    the lines 163-165 branch in _walk that was previously uncovered.

    Each method body uses 8-space indentation so the source is valid Python.
    compile() is called to assert this before the chunker is invoked.
    """
    # 8-space indented body lines — valid inside a class method
    method_body = "        x = 1\n" * 8  # 14 chars * 8 = 112 chars per method body
    code = (
        "class Big:\n"
        "    def alpha(self):\n"
        + method_body
        + "    def beta(self):\n"
        + method_body
        + "    def gamma(self):\n"
        + method_body
    )
    # Sanity: the generated source must be valid Python before we test the chunker
    compile(code, "<test>", "exec")

    # chunk_size=200: each method (~132 chars) fits; the class (~406 chars) does not
    chunker = ASTChunker(_make_settings(chunk_size=200, chunk_overlap=0))
    result = chunker.chunk(code, {"source": "big.py"})
    # The oversized class must NOT be emitted as a single chunk
    assert not any("class Big" in c and "def alpha" in c and "def beta" in c for c in result)
    # Each method must appear in its own chunk
    assert any("def alpha" in c for c in result)
    assert any("def beta" in c for c in result)
    assert any("def gamma" in c for c in result)


@pytest.mark.slow
def test_ast_chunker_oversized_class_retains_non_boundary_content() -> None:
    """Oversized class with class-level attributes AND methods must emit both.

    Regression guard for the gap-extraction fix: the oversized boundary walk
    must emit non-boundary content (class attributes) via byte-range gap
    extraction even when some inner boundary nodes (methods) also produce chunks.
    """
    code = (
        "class Config:\n"
        "    alpha = 1\n"
        "    beta = 2\n"
        "    gamma = 3\n"
        "    delta = 4\n"
        "    def method(self):\n"
        "        pass\n"
    )
    compile(code, "<test>", "exec")

    # chunk_size=80: class (~104 chars) is oversized; method (~35 chars) is not
    chunker = ASTChunker(_make_settings(chunk_size=80, chunk_overlap=0))
    result = chunker.chunk(code, {"source": "config.py"})

    full_text = "\n".join(result)
    # Class-level attributes must not be silently dropped
    assert "alpha" in full_text
    assert "beta" in full_text
    assert "gamma" in full_text
    # Method must appear in its own chunk
    assert any("def method" in c for c in result)
    # Attributes and method must not all collapse into one token-window chunk
    assert not any("alpha" in c and "def method" in c for c in result)


@pytest.mark.slow
def test_ast_chunker_non_ascii_source_chunks_correctly() -> None:
    """Non-ASCII characters before a function must not corrupt the chunk text.

    Regression for the byte-offset slicing bug: tree-sitter node offsets are
    UTF-8 byte offsets, not Python str character offsets.  Indexing a str by
    byte offsets shifts slices for any multi-byte character that precedes the
    node.
    """
    code = "# café résumé\ndef foo():\n    return 42\n"
    chunker = ASTChunker(_make_settings(chunk_size=1500, chunk_overlap=200))
    result = chunker.chunk(code, {"source": "unicode.py"})
    assert len(result) == 1
    assert result[0].startswith("def foo")

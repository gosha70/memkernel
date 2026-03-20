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

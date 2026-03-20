"""Unit tests for content-hash deduplication."""

from __future__ import annotations

import pytest

from memkernel.memory.dedup import compute_content_hash


@pytest.mark.unit
def test_compute_content_hash_is_deterministic() -> None:
    """Same input always produces the same hash."""
    content = "Use PostgreSQL for persistence."
    assert compute_content_hash(content) == compute_content_hash(content)


@pytest.mark.unit
def test_compute_content_hash_different_content() -> None:
    """Different content produces different hashes."""
    h1 = compute_content_hash("alpha")
    h2 = compute_content_hash("beta")
    assert h1 != h2


@pytest.mark.unit
def test_compute_content_hash_same_content() -> None:
    """Identical strings always hash to the same value."""
    content = "Always use ruff for linting."
    assert compute_content_hash(content) == compute_content_hash(content)


@pytest.mark.unit
def test_compute_content_hash_returns_hex_string() -> None:
    """Hash is a 64-character hex string (SHA-256)."""
    h = compute_content_hash("hello")
    assert len(h) == 64
    assert all(c in "0123456789abcdef" for c in h)

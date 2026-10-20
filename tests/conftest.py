"""Shared test fixtures and configuration."""

from __future__ import annotations

import hashlib
import os
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator


class MockEmbedding:
    """Deterministic fake embeddings based on content hash."""

    def __init__(self, dimension: int = 8) -> None:
        self._dimension = dimension

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._hash_embed(t) for t in texts]

    def _hash_embed(self, text: str) -> list[float]:
        h = hashlib.sha256(text.encode()).digest()
        raw = [b / 255.0 for b in h[: self._dimension]]
        norm = sum(x * x for x in raw) ** 0.5
        return [x / norm if norm > 0 else 0.0 for x in raw]

    @property
    def dimension(self) -> int:
        return self._dimension


@pytest.fixture
def mock_embedding() -> MockEmbedding:
    return MockEmbedding()


@pytest.fixture(autouse=True)
def no_real_agent(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Fail any test that reaches the real ``claude``: on a logged-in machine it could start a paid session.

    A fake ``claude`` goes first on PATH (the runner passes PATH through to its sessions). It records the call and
    exits non-zero, and the test fails afterwards. Tests that need an agent use the stub agent or their own PATH.

    It catches only ``claude`` looked up on PATH, which is how the runner's agent command resolves. It does not
    catch a call by absolute path, through ``npx``, or under a PATH of the test's own that has no stub.
    """
    guard = tmp_path_factory.mktemp("no-real-agent")
    calls = guard / "calls"
    fake = guard / "claude"
    fake.write_text(f'#!/bin/sh\necho "$*" >> "{calls}"\nexit 97\n', encoding="utf-8")
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", f"{guard}{os.pathsep}{os.environ.get('PATH', '')}")
    yield
    if calls.exists():
        pytest.fail(f"the test started the real claude CLI (blocked by tests/conftest.py): {calls.read_text()}")

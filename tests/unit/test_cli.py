"""Unit tests for the `memkernel` console entry point (0.4: --version / --help)."""

from __future__ import annotations

from typing import Any

import pytest

from memkernel import __version__
from memkernel.mcp import server as server_module

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("flag", ["--version", "-V"])
def test_version_flag_prints_and_exits_zero(flag: str, capsys: pytest.CaptureFixture[str]) -> None:
    assert server_module.main([flag]) == 0
    assert capsys.readouterr().out == f"memkernel {__version__}\n"


@pytest.mark.parametrize("flag", ["--help", "-h"])
def test_help_flag_prints_usage(flag: str, capsys: pytest.CaptureFixture[str]) -> None:
    assert server_module.main([flag]) == 0
    out = capsys.readouterr().out
    assert out.startswith("usage: memkernel")
    assert "MEMKERNEL_" in out and "Ctrl-C" in out


def test_unknown_argument_is_an_error(capsys: pytest.CaptureFixture[str]) -> None:
    assert server_module.main(["--bogus", "x"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "unknown arguments: --bogus x" in captured.err and "usage: memkernel" in captured.err


@pytest.mark.parametrize(
    ("transport", "expected"),
    [
        ("streamable-http", {"transport": "streamable-http", "host": "127.0.0.1", "port": 9123}),
        ("stdio", {"transport": "stdio"}),
    ],
)
def test_no_arguments_runs_the_server(
    transport: str, expected: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: dict[str, Any] = {}

    class FakeServer:
        def run(self, transport: str, **kwargs: Any) -> None:
            calls.update(transport=transport, **kwargs)

    monkeypatch.setattr(server_module, "create_server", lambda settings: FakeServer())
    monkeypatch.setenv("MEMKERNEL_TRANSPORT", transport)
    monkeypatch.setenv("MEMKERNEL_HOST", "127.0.0.1")
    monkeypatch.setenv("MEMKERNEL_PORT", "9123")
    assert server_module.main([]) == 0
    assert calls == expected

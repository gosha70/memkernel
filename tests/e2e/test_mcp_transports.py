# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""E2E over the real transports: the server runs as a subprocess and a client talks to it over stdio or HTTP."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path

import anyio
import pytest
from mcp import Client, StdioServerParameters
from mcp.types import CallToolResult, TextContent, TextResourceContents

pytestmark = pytest.mark.e2e

REPO_ROOT = Path(__file__).resolve().parents[2]
LAUNCHER = [sys.executable, "-m", "tests.e2e.server_launcher"]
ROUNDTRIP_TIMEOUT_SECONDS = 60
HTTP_START_TIMEOUT_SECONDS = 30
HTTP_STOP_TIMEOUT_SECONDS = 10
LOCALHOST = "127.0.0.1"
CONTENT = "Transport check: the release branch is cut on Thursdays"


def _env(**extra: str) -> dict[str, str]:
    """The server's environment: an ephemeral store under a fresh project id, plus ``extra``."""
    return {
        "PATH": os.environ.get("PATH", ""),
        "HOME": os.environ.get("HOME", ""),
        "PYTHONPATH": str(REPO_ROOT),
        "MEMKERNEL_PROJECT_ID": f"transport_{uuid.uuid4().hex[:8]}",
        "MEMKERNEL_CHROMA_PERSIST_PATH": "",
        **extra,
    }


def _text(result: CallToolResult) -> str:
    item = result.content[0]
    assert isinstance(item, TextContent)
    return item.text


async def _roundtrip(client: Client) -> None:
    """retain, recall finds it, and memory://status counts it."""
    retained = json.loads(_text(await client.call_tool("retain", {"content": CONTENT, "type": "decision"})))
    found = json.loads(_text(await client.call_tool("recall", {"query": "release branch Thursdays", "top_k": 3})))
    assert [hit["ref_id"] for hit in found][:1] == [retained["ref_id"]]
    status = (await client.read_resource("memory://status")).contents[0]
    assert isinstance(status, TextResourceContents)
    assert json.loads(status.text)["memory_count"] == 1


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind((LOCALHOST, 0))
        return int(probe.getsockname()[1])


def _wait_for_port(port: int, process: subprocess.Popen[bytes]) -> None:
    deadline = time.monotonic() + HTTP_START_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise AssertionError(f"the server exited with {process.returncode} before listening")
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            if probe.connect_ex((LOCALHOST, port)) == 0:
                return
        time.sleep(0.1)
    raise AssertionError(f"the server did not listen on {LOCALHOST}:{port} within {HTTP_START_TIMEOUT_SECONDS}s")


async def test_stdio_roundtrip_against_a_server_subprocess() -> None:
    params = StdioServerParameters(command=LAUNCHER[0], args=LAUNCHER[1:], env=_env(), cwd=str(REPO_ROOT))
    with anyio.fail_after(ROUNDTRIP_TIMEOUT_SECONDS):
        async with Client(params) as client:
            await _roundtrip(client)


async def test_streamable_http_roundtrip_against_a_running_server() -> None:
    port = _free_port()
    env = _env(MEMKERNEL_TRANSPORT="streamable-http", MEMKERNEL_HOST=LOCALHOST, MEMKERNEL_PORT=str(port))
    process = subprocess.Popen(LAUNCHER, cwd=REPO_ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)  # noqa: S603
    try:
        _wait_for_port(port, process)
        with anyio.fail_after(ROUNDTRIP_TIMEOUT_SECONDS):
            async with Client(f"http://{LOCALHOST}:{port}/mcp") as client:
                await _roundtrip(client)
    finally:
        process.terminate()
        try:
            process.wait(timeout=HTTP_STOP_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


@pytest.mark.slow
async def test_stdio_roundtrip_against_the_memkernel_command(tmp_path: Path) -> None:
    """The installed ``memkernel`` entry point with the real embedding model (downloads it on first use)."""
    command = Path(sys.executable).with_name("memkernel")
    env = _env(MEMKERNEL_CHROMA_PERSIST_PATH=str(tmp_path / "chroma"))
    env.pop("PYTHONPATH")
    params = StdioServerParameters(command=str(command), args=[], env=env, cwd=str(tmp_path))
    with anyio.fail_after(ROUNDTRIP_TIMEOUT_SECONDS * 5):
        async with Client(params) as client:
            await _roundtrip(client)

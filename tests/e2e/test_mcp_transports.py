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


async def test_the_http_transport_refuses_a_foreign_host_or_origin() -> None:
    """#148: a foreign Host (DNS rebinding) or Origin (a web page) is refused on a loopback bind.

    The SDK already did this for loopback binds; this keeps it from regressing now that memkernel passes its own
    settings. The non-loopback cases are unit tests (test_http_transport_security.py)."""
    import urllib.error
    import urllib.request

    port = _free_port()
    env = _env(MEMKERNEL_TRANSPORT="streamable-http", MEMKERNEL_HOST=LOCALHOST, MEMKERNEL_PORT=str(port))
    process = subprocess.Popen(LAUNCHER, cwd=REPO_ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)  # noqa: S603
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"}).encode()

    def status(headers: dict[str, str]) -> int:
        request = urllib.request.Request(  # noqa: S310 (a loopback URL built here)
            f"http://{LOCALHOST}:{port}/mcp",
            data=body,
            headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream", **headers},
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310
                return int(response.status)
        except urllib.error.HTTPError as error:
            return int(error.code)

    try:
        _wait_for_port(port, process)
        assert status({"Host": "evil.example"}) == 421
        assert status({"Origin": "http://evil.example"}) == 403
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


SHARED_DECISION = "Shared-store check: the integration branch is frozen on Fridays"


async def _retain_then_recall_elsewhere(writer: Client, reader: Client) -> None:
    """A decision retained through one client is returned by a relevance recall through the other (#107 SC-1, SC-2)."""
    retained = json.loads(_text(await writer.call_tool("retain", {"content": SHARED_DECISION, "type": "decision"})))
    found = json.loads(_text(await reader.call_tool("recall", {"query": "integration branch frozen", "top_k": 3})))
    assert retained["ref_id"] in [hit["ref_id"] for hit in found]


async def test_two_stdio_servers_on_one_store_see_each_others_writes(tmp_path: Path) -> None:
    """#107 FR-001: each tool starts its own memkernel on the shared store; both servers run before the write."""
    env = _env(
        MEMKERNEL_PROJECT_ID="shared_store",
        MEMKERNEL_CHROMA_PERSIST_PATH=str(tmp_path / "chroma"),
        MEMKERNEL_STATE_DIR=str(tmp_path / "state"),
    )
    params = StdioServerParameters(command=LAUNCHER[0], args=LAUNCHER[1:], env=env, cwd=str(REPO_ROOT))
    with anyio.fail_after(ROUNDTRIP_TIMEOUT_SECONDS * 2):
        async with Client(params) as first, Client(params) as second:
            await second.call_tool("recall", {"query": "warm up", "top_k": 1})  # the second server is live first
            await _retain_then_recall_elsewhere(first, second)


async def test_two_clients_share_one_http_server() -> None:
    """#107 FR-002: one long-running server, registered in each tool."""
    port = _free_port()
    env = _env(MEMKERNEL_TRANSPORT="streamable-http", MEMKERNEL_HOST=LOCALHOST, MEMKERNEL_PORT=str(port))
    process = subprocess.Popen(LAUNCHER, cwd=REPO_ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)  # noqa: S603
    try:
        _wait_for_port(port, process)
        with anyio.fail_after(ROUNDTRIP_TIMEOUT_SECONDS):
            url = f"http://{LOCALHOST}:{port}/mcp"
            async with Client(url) as first, Client(url) as second:
                await _retain_then_recall_elsewhere(first, second)
    finally:
        process.terminate()
        try:
            process.wait(timeout=HTTP_STOP_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()

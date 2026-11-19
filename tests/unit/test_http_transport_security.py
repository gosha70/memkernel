# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""The HTTP transport's Host/Origin check follows MEMKERNEL_HOST (#148)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from memkernel.config import MemKernelSettings
from memkernel.mcp.server import transport_security

if TYPE_CHECKING:
    from mcp.server.transport_security import TransportSecuritySettings

pytestmark = pytest.mark.unit


def _security(host: str, allowed: str = "") -> TransportSecuritySettings | None:
    return transport_security(MemKernelSettings(host=host, allowed_hosts=allowed, chroma_persist_path=""))


def _checked(host: str, allowed: str = "") -> TransportSecuritySettings:
    settings = _security(host, allowed)
    assert settings is not None
    return settings


def test_a_loopback_host_allows_only_loopback_names(caplog: pytest.LogCaptureFixture) -> None:
    settings = _checked("127.0.0.1")
    assert settings.enable_dns_rebinding_protection
    assert set(settings.allowed_hosts) == {"127.0.0.1", "127.0.0.1:*", "localhost", "localhost:*", "[::1]", "[::1]:*"}
    assert "http://localhost:*" in settings.allowed_origins
    assert not [r for r in caplog.records if "authentication" in r.message]


def test_ipv6_loopback_is_bracketed() -> None:
    settings = _checked("::1")
    assert "[::1]:*" in settings.allowed_hosts


def test_a_specific_address_is_allowed_with_a_warning(caplog: pytest.LogCaptureFixture) -> None:
    settings = _checked("192.168.1.20", "memkernel.lan")
    assert {"192.168.1.20:*", "memkernel.lan:*"} <= set(settings.allowed_hosts)
    assert "localhost:*" not in settings.allowed_hosts
    assert any("no authentication" in r.message for r in caplog.records)


def test_a_wildcard_bind_needs_allowed_hosts(caplog: pytest.LogCaptureFixture) -> None:
    assert _security("0.0.0.0") is None  # unchecked, as before, so Docker setups keep working
    assert any("MEMKERNEL_ALLOWED_HOSTS" in r.message for r in caplog.records)
    settings = _checked("0.0.0.0", "my-box, my-box.local")
    assert {"my-box:*", "my-box.local:*"} <= set(settings.allowed_hosts)
    assert {"127.0.0.1:*", "localhost:*"} <= set(settings.allowed_hosts)  # local tools still reach a wildcard bind
    assert "0.0.0.0:*" not in settings.allowed_hosts


def test_origins_cover_the_default_port() -> None:
    settings = _checked("192.168.1.20", "my-box")
    assert {"http://my-box", "http://my-box:*", "https://my-box", "https://my-box:*"} <= set(settings.allowed_origins)

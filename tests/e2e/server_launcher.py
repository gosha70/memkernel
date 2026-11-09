# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""Start memkernel's MCP server for the transport tests: the real server and transport, the tests' embedding.

Run as ``python -m tests.e2e.server_launcher`` from the repository root. Settings come from ``MEMKERNEL_*``
environment variables, as for the ``memkernel`` command; only the embedding is the tests' ``MockEmbedding``, so no
model is downloaded.
"""

from __future__ import annotations

from memkernel.config import MemKernelSettings
from memkernel.mcp.server import create_server, run_server
from tests.conftest import MockEmbedding

EMBEDDING_DIMENSION = 384


def main() -> None:
    settings = MemKernelSettings()
    run_server(create_server(settings, MockEmbedding(dimension=EMBEDDING_DIMENSION)), settings)


if __name__ == "__main__":
    main()

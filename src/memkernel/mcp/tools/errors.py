# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""Tool errors the client should read.

mcp 2.x sends the client the text of a ``ToolError`` only; any other exception is reported as a bare
"Error executing tool <name>". memkernel signals a caller's mistake (an unknown mode, a missing wiki directory, a
misused argument) with ``ValueError``, so those become ``ToolError`` and keep their message. Anything else stays
hidden, as mcp 2.x intends for crashes.
"""

from __future__ import annotations

import functools
from typing import TYPE_CHECKING, Any, TypeVar

from mcp.server.mcpserver.exceptions import ToolError

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

_T = TypeVar("_T")


def reported_errors(fn: Callable[..., Coroutine[Any, Any, _T]]) -> Callable[..., Coroutine[Any, Any, _T]]:
    """Re-raise a tool's ``ValueError`` as ``ToolError`` with the same message."""

    @functools.wraps(fn)
    async def wrapper(*args: Any, **kwargs: Any) -> _T:
        try:
            return await fn(*args, **kwargs)
        except ValueError as exc:
            raise ToolError(str(exc)) from exc

    return wrapper

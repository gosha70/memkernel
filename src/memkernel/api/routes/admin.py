# Copyright (c) EGOGE - All Rights Reserved.
# This software may be used and distributed according to the terms of the MIT license.
"""Admin API route handlers: /health, /stats, /collections."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Request

if TYPE_CHECKING:
    from memkernel.core.services import MemoryService

router = APIRouter()


def _svc(request: Request) -> MemoryService:
    return request.app.state.memory_service  # type: ignore[no-any-return]


@router.get("/health")
async def health(request: Request) -> dict[str, Any]:
    """Server liveness check: status, collection count, memory count."""
    svc = _svc(request)
    return {
        "status": "ok",
        "project_id": svc.project_id,
        "collection_count": svc.collection_count(),
        "memory_count": svc.count(),
    }


@router.get("/stats")
async def stats(request: Request) -> dict[str, Any]:
    """Memory metrics: per-type breakdown, growth by time window, last recall latency."""
    svc = _svc(request)
    return svc.stats()


@router.get("/collections")
async def collections(request: Request) -> list[dict[str, Any]]:
    """List all project collections with record counts."""
    svc = _svc(request)
    return svc.list_collections()

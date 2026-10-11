# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""FastAPI admin API factory and entry point.

Production:
    uvicorn memkernel.api.app:app --reload

Tests inject a pre-built MemoryService via create_app(memory_service=svc).
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from fastapi import FastAPI

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from memkernel.core.services import MemoryService

logger = logging.getLogger(__name__)


def create_app(memory_service: MemoryService | None = None) -> FastAPI:
    """FastAPI app factory.

    Tests pass a pre-built MemoryService (with EphemeralClient, MockEmbedding).
    Production calls with None — MemoryService is built from env at startup.
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if memory_service is not None:
            app.state.memory_service = memory_service
        else:
            app.state.memory_service = _build_service()
            logger.info("MemoryService initialised for project %s", app.state.memory_service.project_id)
        yield

    application: FastAPI = FastAPI(
        title="MemKernel Admin API",
        version="0.1.0",
        lifespan=lifespan,
    )

    from memkernel.api.routes.admin import router

    application.include_router(router)
    return application


def _build_service() -> MemoryService:
    """Construct MemoryService from environment settings (production only)."""
    from memkernel.factory import build_service

    return build_service()


# Module-level app for `uvicorn memkernel.api.app:app`
# MemoryService is built lazily in the lifespan — safe to import without real deps.
app = create_app()

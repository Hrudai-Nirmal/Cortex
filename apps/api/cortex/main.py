"""FastAPI application factory with explicit middleware and domain error boundaries."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import cortex.api.routes as routeModule
from cortex.api.routes import router
from cortex.config import Settings, getSettings
from cortex.logging_config import configureLogging, getLogger

logger = getLogger("api")


def createApp(settingsOverride: Settings | None = None) -> FastAPI:
    """Create the Cortex API without performing network operations at import time."""
    configureLogging()
    activeSettings = settingsOverride or getSettings()
    routeModule.settings = activeSettings

    @asynccontextmanager
    async def applicationLifespan(_: FastAPI):
        logger.info(
            "api_startup_profile",
            environment=activeSettings.environment,
            consoleHost=activeSettings.consoleHost,
            queryHost=activeSettings.queryHost,
            objectStorageRoot=activeSettings.objectStorageRoot,
            requiredAccelerator=activeSettings.requiredAccelerator,
            ollamaBaseUrl=activeSettings.ollamaBaseUrl,
            corsOrigins=list(activeSettings.getCorsOrigins()),
        )
        yield

    application = FastAPI(
        title="Cortex API",
        version="0.1.0",
        description="Evidence-bounded enterprise RAG control plane",
        lifespan=applicationLifespan,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=list(activeSettings.getCorsOrigins()),
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Cortex-Enterprise"],
    )
    application.state.settings = activeSettings
    application.include_router(router)
    return application


app = createApp()

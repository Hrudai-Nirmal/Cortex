"""FastAPI application factory with explicit middleware and domain error boundaries."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import cortex.api.routes as routeModule
from cortex.api.routes import router
from cortex.config import Settings, getSettings
from cortex.logging_config import configureLogging, getLogger
from cortex.services.model_provider import OllamaModelProvider
from cortex.services.runtime import RuntimeHealthService

logger = getLogger("api")


def shouldFailClosedOnStartup(settings: Settings) -> bool:
    """Fail packaged API processes on degraded static startup health in production profiles."""
    return settings.environment == "production" and not settings.devMode


def buildApiModelProvider(settings: Settings) -> OllamaModelProvider:
    """Create the local model provider used by startup-safe API validation."""
    return OllamaModelProvider(
        baseUrl=settings.ollamaBaseUrl,
        generatorModel=settings.generatorModel,
        embeddingModel=settings.embeddingModel,
    )


def buildStartupExceptionMessage(prefix: str, error: Exception) -> str:
    """Preserve the underlying startup exception text for operator troubleshooting."""
    normalizedDetail = str(error).strip() or error.__class__.__name__
    return f"{prefix}: {normalizedDetail}"


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
        try:
            startupHealth = await RuntimeHealthService(
                session=None,
                settings=activeSettings,
                modelProvider=buildApiModelProvider(activeSettings),
            ).getStartupReadiness()
        except Exception as error:
            logger.error("api_startup_health_error", error=str(error))
            raise RuntimeError(
                buildStartupExceptionMessage(
                    "api startup could not collect startup readiness",
                    error,
                )
            ) from error
        logger.info(
            "api_startup_health",
            status=startupHealth.status,
            environment=startupHealth.environment,
            components=RuntimeHealthService.serializeRuntimeComponents(startupHealth.components),
        )
        failingComponents = RuntimeHealthService.getFailingComponents(startupHealth)
        if failingComponents:
            failureMessage = RuntimeHealthService.buildFailureMessage(
                "api startup blocked by runtime health checks",
                failingComponents,
            )
            if shouldFailClosedOnStartup(activeSettings):
                logger.error(
                    "api_startup_blocked",
                    components=RuntimeHealthService.serializeRuntimeComponents(
                        failingComponents
                    ),
                )
                raise RuntimeError(failureMessage)
            logger.warning(
                "api_startup_degraded",
                components=RuntimeHealthService.serializeRuntimeComponents(failingComponents),
                message=failureMessage,
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

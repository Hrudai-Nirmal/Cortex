"""Worker startup tests keep durable processing from running on a broken package runtime."""

from __future__ import annotations

from contextlib import asynccontextmanager

import pytest

import cortex.worker as workerModule
from cortex.config import Settings
from cortex.errors import WorkerStartupError
from cortex.schemas import RuntimeComponentSchema, RuntimeHealthResponse


def buildWorkerSettings() -> Settings:
    """Create one worker settings profile without relying on ambient developer env vars."""
    return Settings(
        environment="test",
        devMode=False,
        requiredAccelerator="cpu",
        databaseUrl="postgresql+asyncpg://cortex:cortex@postgres:5432/cortex",
        ollamaBaseUrl="http://ollama:11434",
        objectStorageRoot=".cortex-data/test-object-storage",
        consoleHost="console.example.test",
        queryHost="query.example.test",
        consolePublicUrl="https://console.example.test",
        queryPublicUrl="https://query.example.test",
    )


def buildRuntimeHealth(*components: RuntimeComponentSchema) -> RuntimeHealthResponse:
    """Assemble one runtime-health payload for worker-startup tests."""
    return RuntimeHealthResponse(
        status="ready" if all(component.status == "ready" for component in components) else "degraded",
        environment="test",
        components=list(components),
    )


@pytest.mark.asyncio
async def testValidateWorkerStartupRaisesForStaticHealthFailures(monkeypatch) -> None:
    """The worker must fail fast when startup-safe deployment checks already disagree."""

    class StubRuntimeHealthService:
        """Return one degraded startup payload without touching live dependencies."""

        def __init__(self, session, settings, modelProvider) -> None:
            self.session = session

        async def getStartupReadiness(self) -> RuntimeHealthResponse:
            return buildRuntimeHealth(
                RuntimeComponentSchema(
                    name="model-endpoint-policy",
                    status="degraded",
                    severity="error",
                    detail="model endpoint host example.com is not local or private",
                    remediation="Point CORTEX_OLLAMA_BASE_URL at a local or private endpoint.",
                )
            )

        async def getReadiness(self) -> RuntimeHealthResponse:
            raise AssertionError("live readiness should not run when static startup already failed")

        @staticmethod
        def getFailingComponents(runtimeHealth: RuntimeHealthResponse) -> list[RuntimeComponentSchema]:
            return [
                component for component in runtimeHealth.components if component.status != "ready"
            ]

    monkeypatch.setattr(workerModule, "RuntimeHealthService", StubRuntimeHealthService)

    with pytest.raises(WorkerStartupError, match="model-endpoint-policy"):
        await workerModule.validateWorkerStartup(buildWorkerSettings())


@pytest.mark.asyncio
async def testValidateWorkerStartupRaisesForLiveReadinessFailures(monkeypatch) -> None:
    """The worker must refuse to poll when database/model readiness is degraded."""

    class StubRuntimeHealthService:
        """Return one clean startup report and one degraded live readiness report."""

        def __init__(self, session, settings, modelProvider) -> None:
            self.session = session

        async def getStartupReadiness(self) -> RuntimeHealthResponse:
            return buildRuntimeHealth(
                RuntimeComponentSchema(
                    name="deployment-config",
                    status="ready",
                    severity="info",
                    detail="console=https://console.example.test",
                    remediation=None,
                )
            )

        async def getReadiness(self) -> RuntimeHealthResponse:
            return buildRuntimeHealth(
                RuntimeComponentSchema(
                    name="postgresql",
                    status="degraded",
                    severity="error",
                    detail="database ready but pgvector extension is missing",
                    remediation="Install or enable the PostgreSQL vector extension.",
                )
            )

        @staticmethod
        def getFailingComponents(runtimeHealth: RuntimeHealthResponse) -> list[RuntimeComponentSchema]:
            return [
                component for component in runtimeHealth.components if component.status != "ready"
            ]

    @asynccontextmanager
    async def stubSessionFactory():
        yield object()

    monkeypatch.setattr(workerModule, "RuntimeHealthService", StubRuntimeHealthService)
    monkeypatch.setattr(workerModule, "sessionFactory", stubSessionFactory)

    with pytest.raises(WorkerStartupError, match="postgresql"):
        await workerModule.validateWorkerStartup(buildWorkerSettings())

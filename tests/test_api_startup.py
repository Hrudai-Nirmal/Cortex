"""API startup tests keep packaged deployments fail-closed without breaking development flow."""

from __future__ import annotations

import pytest

import cortex.main as mainModule
from cortex.config import Settings
from cortex.main import createApp
from cortex.schemas import RuntimeComponentSchema, RuntimeHealthResponse


def buildSettings(**overrides: object) -> Settings:
    """Create one deterministic runtime profile for API-startup tests."""
    values = {
        "environment": "production",
        "devMode": False,
        "requiredAccelerator": "cpu",
        "databaseUrl": "postgresql+asyncpg://cortex:cortex@postgres:5432/cortex",
        "ollamaBaseUrl": "http://ollama:11434",
        "objectStorageRoot": "/var/lib/cortex/object-storage",
        "consoleHost": "cortex-console.client.internal",
        "queryHost": "cortex-app.client.internal",
        "consolePublicUrl": "https://cortex-console.client.internal",
        "queryPublicUrl": "https://cortex-app.client.internal",
    }
    values.update(overrides)
    return Settings(**values)


@pytest.mark.asyncio
async def testProductionApiStartupRaisesForDegradedStaticHealth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Packaged production APIs should refuse to boot when startup-safe health is degraded."""

    async def stubStartupReadiness(self) -> RuntimeHealthResponse:
        return RuntimeHealthResponse(
            status="degraded",
            environment="production",
            components=[
                RuntimeComponentSchema(
                    name="object-storage",
                    status="unavailable",
                    severity="error",
                    detail="/var/lib/cortex/object-storage: read-only file system",
                    remediation="Mount a writable persistent volume.",
                )
            ],
        )

    monkeypatch.setattr(mainModule.RuntimeHealthService, "getStartupReadiness", stubStartupReadiness)

    application = createApp(buildSettings())

    with pytest.raises(RuntimeError, match="api startup blocked by runtime health checks"):
        async with application.router.lifespan_context(application):
            pass


@pytest.mark.asyncio
async def testDevelopmentApiStartupLogsButAllowsDegradedStaticHealth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Development APIs should stay bootable even when startup health is degraded."""

    async def stubStartupReadiness(self) -> RuntimeHealthResponse:
        return RuntimeHealthResponse(
            status="degraded",
            environment="development",
            components=[
                RuntimeComponentSchema(
                    name="parser-dependencies",
                    status="degraded",
                    severity="error",
                    detail="Docling unavailable",
                    remediation="Install ingestion dependencies before enabling source onboarding.",
                )
            ],
        )

    monkeypatch.setattr(mainModule.RuntimeHealthService, "getStartupReadiness", stubStartupReadiness)

    application = createApp(
        buildSettings(
            environment="development",
            devMode=True,
            objectStorageRoot=".cortex-data/test-object-storage",
            consoleHost="127.0.0.1",
            queryHost="127.0.0.1",
            consolePublicUrl="http://127.0.0.1:5173",
            queryPublicUrl="http://127.0.0.1:5174",
        )
    )

    async with application.router.lifespan_context(application):
        pass


@pytest.mark.asyncio
async def testProductionApiStartupPreservesStartupReadinessExceptionContext(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Packaged production APIs should preserve the underlying startup-check exception clue."""

    async def stubStartupReadiness(self) -> RuntimeHealthResponse:
        raise RuntimeError("model endpoint handshake timed out")

    monkeypatch.setattr(mainModule.RuntimeHealthService, "getStartupReadiness", stubStartupReadiness)

    application = createApp(buildSettings())

    with pytest.raises(
        RuntimeError,
        match="model endpoint handshake timed out",
    ) as errorInfo:
        async with application.router.lifespan_context(application):
            pass

    assert "api startup could not collect startup readiness" in str(errorInfo.value)

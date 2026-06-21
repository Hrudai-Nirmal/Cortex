"""Deployment and external query contract tests protect the shippable package boundary."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

from cortex.config import Settings
from cortex.main import createApp
from cortex.services.model_provider import OllamaModelProvider
from cortex.services.runtime import RuntimeHealthService


def buildPackageSettings(**overrides: object) -> Settings:
    """Create one package-style settings object with distinct split-host defaults."""
    baseValues = {
        "environment": "production",
        "devMode": False,
        "requiredAccelerator": "cpu",
        "databaseUrl": "postgresql+asyncpg://cortex:cortex@postgres:5432/cortex",
        "ollamaBaseUrl": "http://ollama:11434",
        "objectStorageRoot": "/var/lib/cortex/object-storage",
        "consoleHost": "cortex-console.example.com",
        "queryHost": "cortex-app.example.com",
        "consolePublicUrl": "https://cortex-console.example.com",
        "queryPublicUrl": "https://cortex-app.example.com",
    }
    baseValues.update(overrides)
    return Settings(**baseValues)


def testProductionSettingsRejectLocalhostHosts() -> None:
    """Production packages must not accidentally keep developer localhost domains."""
    with pytest.raises(ValidationError):
        buildPackageSettings(
            consoleHost="localhost",
            consolePublicUrl="http://localhost:5173",
        )


@pytest.mark.asyncio
async def testConfiguredQueryOriginIsAllowedByCors() -> None:
    """Replacement query shells on the configured host must be able to call the API."""
    application = createApp(buildPackageSettings())
    async with AsyncClient(
        transport=ASGITransport(app=application),
        base_url="http://testserver",
    ) as client:
        response = await client.options(
            "/v1/session",
            headers={
                "Origin": "https://cortex-app.example.com",
                "Access-Control-Request-Method": "GET",
            },
        )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://cortex-app.example.com"


@pytest.mark.asyncio
async def testStartupHealthFlagsUnexpectedRemoteModelEndpoints() -> None:
    """Offline-capable packages should warn operators before using public model endpoints."""
    settings = buildPackageSettings(ollamaBaseUrl="https://api.openai.example.com")
    runtimeHealth = await RuntimeHealthService(
        session=None,
        settings=settings,
        modelProvider=OllamaModelProvider(
            baseUrl=settings.ollamaBaseUrl,
            generatorModel=settings.generatorModel,
            embeddingModel=settings.embeddingModel,
        ),
    ).getStartupReadiness()
    policyComponent = next(
        component
        for component in runtimeHealth.components
        if component.name == "model-endpoint-policy"
    )
    assert runtimeHealth.status == "degraded"
    assert policyComponent.status == "degraded"
    assert policyComponent.severity == "error"
    assert "ALLOW_REMOTE_MODEL_ENDPOINT" in policyComponent.detail
    assert policyComponent.remediation is not None
    assert "CORTEX_OLLAMA_BASE_URL" in policyComponent.remediation


@pytest.mark.asyncio
async def testStartupHealthTreatsWebsiteAllowlistAsOptionalCapability() -> None:
    """Uploads-only deployments should stay ready while still documenting website ingestion."""
    settings = buildPackageSettings(websiteAllowlist=())
    runtimeHealth = await RuntimeHealthService(
        session=None,
        settings=settings,
        modelProvider=OllamaModelProvider(
            baseUrl=settings.ollamaBaseUrl,
            generatorModel=settings.generatorModel,
            embeddingModel=settings.embeddingModel,
        ),
    ).getStartupReadiness()
    websiteComponent = next(
        component
        for component in runtimeHealth.components
        if component.name == "website-ingestion"
    )
    assert websiteComponent.status == "ready"
    assert "uploads remain available" in websiteComponent.detail
    assert websiteComponent.remediation is not None

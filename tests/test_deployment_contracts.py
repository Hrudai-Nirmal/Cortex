"""Deployment and external query contract tests protect the shippable package boundary."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

import cortex.api.routes as routeModule
import cortex.services.runtime as runtimeModule
from cortex.config import Settings
from cortex.database import getDatabaseSession
from cortex.main import createApp
from cortex.schemas import QueryResponse, StageSchema
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


def testProductionSettingsRequireAbsoluteObjectStorageRoot() -> None:
    """Client package profiles should reject relative object-storage paths in production."""
    with pytest.raises(ValidationError):
        buildPackageSettings(objectStorageRoot=".cortex-data/object-storage")


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
async def testStartupHealthAllowsExplicitRemoteModelEndpoints() -> None:
    """Packages may opt into remote model endpoints only through an explicit override."""
    settings = buildPackageSettings(
        ollamaBaseUrl="https://models.internal.example.com",
        allowRemoteModelEndpoint=True,
    )
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
    assert policyComponent.status == "ready"
    assert policyComponent.severity == "info"
    assert "remote model endpoints permitted" in policyComponent.detail
    assert policyComponent.remediation is not None


@pytest.mark.asyncio
async def testStartupHealthReportsDeclaredModelProfile() -> None:
    """Operators should be able to see the packaged generator, embedding, and accelerator profile."""
    settings = buildPackageSettings(
        generatorModel="qwen3:8b",
        embeddingModel="qwen3-embedding:0.6b",
        requiredAccelerator="cpu",
    )
    runtimeHealth = await RuntimeHealthService(
        session=None,
        settings=settings,
        modelProvider=OllamaModelProvider(
            baseUrl=settings.ollamaBaseUrl,
            generatorModel=settings.generatorModel,
            embeddingModel=settings.embeddingModel,
        ),
    ).getStartupReadiness()
    profileComponent = next(
        component for component in runtimeHealth.components if component.name == "model-profile"
    )
    assert profileComponent.status == "ready"
    assert profileComponent.severity == "info"
    assert "generator=qwen3:8b" in profileComponent.detail
    assert "embedding=qwen3-embedding:0.6b" in profileComponent.detail
    assert "requiredAccelerator=cpu" in profileComponent.detail
    assert profileComponent.remediation is not None


@pytest.mark.asyncio
async def testStartupHealthReportsDeclaredIdentityProfile() -> None:
    """Operators should be able to see the declared auth mode and OIDC contract."""
    settings = buildPackageSettings()
    runtimeHealth = await RuntimeHealthService(
        session=None,
        settings=settings,
        modelProvider=OllamaModelProvider(
            baseUrl=settings.ollamaBaseUrl,
            generatorModel=settings.generatorModel,
            embeddingModel=settings.embeddingModel,
        ),
    ).getStartupReadiness()
    identityComponent = next(
        component for component in runtimeHealth.components if component.name == "identity-profile"
    )
    assert identityComponent.status == "ready"
    assert identityComponent.severity == "info"
    assert "authMode=fixture" in identityComponent.detail
    assert f"oidcIssuer={settings.oidcIssuerUrl}" in identityComponent.detail
    assert f"oidcAudience={settings.oidcAudience}" in identityComponent.detail
    assert identityComponent.remediation is not None


@pytest.mark.asyncio
async def testStartupHealthFlagsObjectStorageWriteFailures(tmp_path: pytest.TempPathFactory) -> None:
    """Packages should report an operator-facing error when object storage is not writable."""
    blockedPath = tmp_path / "blocked-root"
    blockedPath.write_text("not a directory", encoding="utf-8")
    settings = buildPackageSettings(objectStorageRoot=str(blockedPath))
    runtimeHealth = await RuntimeHealthService(
        session=None,
        settings=settings,
        modelProvider=OllamaModelProvider(
            baseUrl=settings.ollamaBaseUrl,
            generatorModel=settings.generatorModel,
            embeddingModel=settings.embeddingModel,
        ),
    ).getStartupReadiness()
    storageComponent = next(
        component for component in runtimeHealth.components if component.name == "object-storage"
    )
    assert runtimeHealth.status == "degraded"
    assert storageComponent.status == "unavailable"
    assert storageComponent.severity == "error"
    assert storageComponent.remediation is not None
    assert "persistent volume" in storageComponent.remediation


@pytest.mark.asyncio
async def testStartupHealthFlagsAcceleratorMismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Declared accelerator expectations should fail closed when the runtime disagrees."""
    monkeypatch.setattr(runtimeModule, "detectAvailableAccelerator", lambda: "cpu")
    settings = buildPackageSettings(requiredAccelerator="mps")
    runtimeHealth = await RuntimeHealthService(
        session=None,
        settings=settings,
        modelProvider=OllamaModelProvider(
            baseUrl=settings.ollamaBaseUrl,
            generatorModel=settings.generatorModel,
            embeddingModel=settings.embeddingModel,
        ),
    ).getStartupReadiness()
    acceleratorComponent = next(
        component for component in runtimeHealth.components if component.name == "accelerator"
    )
    assert runtimeHealth.status == "degraded"
    assert acceleratorComponent.status == "degraded"
    assert acceleratorComponent.severity == "error"
    assert "required mps, detected cpu" in acceleratorComponent.detail
    assert acceleratorComponent.remediation is not None


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


@pytest.mark.asyncio
async def testExternalChatContractRejectsStreamingRequests() -> None:
    """Replacement chat shells must use the non-streaming facade and trace SSE separately."""
    application = createApp(buildPackageSettings())

    async def overrideDatabaseSession():
        yield object()

    application.dependency_overrides[getDatabaseSession] = overrideDatabaseSession

    async with AsyncClient(
        transport=ASGITransport(app=application),
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            "/v1/chat/completions",
            headers={"Authorization": "Bearer fixture-employee"},
            json={
                "model": "cortex-bounded-rag",
                "messages": [{"role": "user", "content": "What are our retention rules?"}],
                "stream": True,
                "cortex": {"showCitations": True},
            },
        )

    assert response.status_code == 422
    assert "SSE trace events" in response.json()["detail"]


@pytest.mark.asyncio
async def testExternalChatContractUsesLatestUserMessageAndReturnsEvidenceMetadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Replacement query shells should get stable evidence metadata from the chat facade."""
    application = createApp(buildPackageSettings())
    capturedRequestQuery: dict[str, str] = {}

    async def overrideDatabaseSession():
        yield object()

    class StubQueryService:
        """Return one deterministic query answer without touching live dependencies."""

        def __init__(self, session, settings, modelProvider) -> None:
            self.session = session

        async def answerQuery(self, request) -> QueryResponse:
            capturedRequestQuery["value"] = request.query
            return QueryResponse(
                traceId="4576b626-c27a-4409-9a51-600cf115ff4a",
                route="rag",
                correctedQuery="What are our retention rules?",
                answer="Raw query content is retained for 30 days.",
                evidenceStatus="sufficient",
                claims=[],
                citations=[],
                stages=[
                    StageSchema(
                        name="Scoped hybrid retrieval",
                        status="complete",
                        durationMs=120,
                        detail="4 authorized candidates after threshold",
                    )
                ],
            )

    monkeypatch.setattr(routeModule, "QueryService", StubQueryService)
    application.dependency_overrides[getDatabaseSession] = overrideDatabaseSession

    async with AsyncClient(
        transport=ASGITransport(app=application),
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            "/v1/chat/completions",
            headers={"Authorization": "Bearer fixture-employee"},
            json={
                "model": "cortex-bounded-rag",
                "messages": [
                    {"role": "system", "content": "You are the company assistant."},
                    {"role": "user", "content": "Ignore this older prompt."},
                    {"role": "assistant", "content": "Earlier answer."},
                    {"role": "user", "content": "  What are our retentin rules?  "},
                ],
                "stream": False,
                "cortex": {"showCitations": True},
            },
        )

    payload = response.json()
    assert response.status_code == 200
    assert capturedRequestQuery["value"] == "What are our retentin rules?"
    assert payload["choices"][0]["message"]["content"] == "Raw query content is retained for 30 days."
    assert response.headers["x-cortex-contract-version"] == "v1"
    assert response.headers["x-cortex-trace-id"] == "4576b626-c27a-4409-9a51-600cf115ff4a"
    assert response.headers["x-cortex-evidence-status"] == "sufficient"
    assert payload["x_cortex"]["contractVersion"] == "v1"
    assert payload["x_cortex"]["traceId"] == "4576b626-c27a-4409-9a51-600cf115ff4a"
    assert (
        payload["x_cortex"]["traceEventsPath"]
        == "/v1/query/4576b626-c27a-4409-9a51-600cf115ff4a/events"
    )
    assert payload["x_cortex"]["correctedQuery"] == "What are our retention rules?"
    assert payload["x_cortex"]["evidenceStatus"] == "sufficient"
    assert payload["x_cortex"]["abstained"] is False
    assert payload["x_cortex"]["stages"][0]["name"] == "Scoped hybrid retrieval"


@pytest.mark.asyncio
async def testExternalChatContractPreservesAbstentionAndCitationMetadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Replacement chat shells should receive stable abstention, claim, and citation signals."""
    application = createApp(buildPackageSettings())

    async def overrideDatabaseSession():
        yield object()

    class StubQueryService:
        """Return one deterministic abstention response without touching live dependencies."""

        def __init__(self, session, settings, modelProvider) -> None:
            self.session = session

        async def answerQuery(self, request) -> QueryResponse:
            return QueryResponse(
                traceId="8b24db0b-bccd-4b45-9073-60c35fd8347b",
                route="rag",
                correctedQuery=request.query,
                answer="I do not have enough consistent evidence to answer that safely.",
                evidenceStatus="conflict",
                claims=[
                    {
                        "claimId": "claim-1",
                        "text": "Retention is 180 days.",
                        "confidence": 0.42,
                        "citationIds": ["citation-1"],
                        "supportStatus": "conflict",
                    }
                ],
                citations=[
                    {
                        "citationId": "citation-1",
                        "documentTitle": "Security Handbook",
                        "documentVersion": "v2",
                        "chunkId": "abc123",
                        "structuralLocator": "p.12",
                        "exactSpan": "Retention differs between systems.",
                        "supportScore": 0.41,
                    }
                ],
                stages=[
                    StageSchema(
                        name="Claim validation",
                        status="complete",
                        durationMs=45,
                        detail="conflicting evidence remained after validation",
                    )
                ],
            )

    monkeypatch.setattr(routeModule, "QueryService", StubQueryService)
    application.dependency_overrides[getDatabaseSession] = overrideDatabaseSession

    async with AsyncClient(
        transport=ASGITransport(app=application),
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            "/v1/chat/completions",
            headers={"Authorization": "Bearer fixture-employee"},
            json={
                "model": "cortex-bounded-rag",
                "messages": [{"role": "user", "content": "What is the retention period?"}],
                "stream": False,
                "cortex": {"showCitations": True},
            },
        )

    payload = response.json()
    assert response.status_code == 200
    assert response.headers["x-cortex-contract-version"] == "v1"
    assert response.headers["x-cortex-evidence-status"] == "conflict"
    assert payload["x_cortex"]["abstained"] is True
    assert payload["x_cortex"]["claims"][0]["supportStatus"] == "conflict"
    assert payload["x_cortex"]["citations"][0]["documentTitle"] == "Security Handbook"
    assert payload["x_cortex"]["traceEventsPath"] == "/v1/query/8b24db0b-bccd-4b45-9073-60c35fd8347b/events"

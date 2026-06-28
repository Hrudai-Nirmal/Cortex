"""Deployment and external query contract tests protect the shippable package boundary."""

from __future__ import annotations

from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

import cortex.api.routes as routeModule
import cortex.services.runtime as runtimeModule
from cortex.config import Settings
from cortex.database import getDatabaseSession
from cortex.errors import ProviderOperationError
from cortex.main import createApp
from cortex.schemas import (
    QueryResponse,
    RuntimeComponentSchema,
    RuntimeHealthResponse,
    SeedFixturesResponse,
    StageSchema,
)
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
        "consoleHost": "cortex-console.client.internal",
        "queryHost": "cortex-app.client.internal",
        "consolePublicUrl": "https://cortex-console.client.internal",
        "queryPublicUrl": "https://cortex-app.client.internal",
        "querySurfaceMode": "bundled",
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


def testProductionSettingsRequireHttpsPublicUrls() -> None:
    """Client browser surfaces should not ship as plaintext HTTP in production."""
    with pytest.raises(ValidationError):
        buildPackageSettings(consolePublicUrl="http://cortex-console.client.internal")


def testProductionSettingsRejectDocumentationPlaceholderDomains() -> None:
    """Package runtime settings must force operators to replace example hosts before boot."""
    with pytest.raises(ValidationError):
        buildPackageSettings(consoleHost="cortex-console.example.com")


def testProductionSettingsRejectPublicUrlsWithPaths() -> None:
    """Split-host public URLs should stay rooted at the host, not a nested path."""
    with pytest.raises(ValidationError):
        buildPackageSettings(queryPublicUrl="https://cortex-app.client.internal/ask")


def testProductionSettingsRequireAbsoluteObjectStorageRoot() -> None:
    """Client package profiles should reject relative object-storage paths in production."""
    with pytest.raises(ValidationError):
        buildPackageSettings(objectStorageRoot=".cortex-data/object-storage")


def testPackagedEdgeTemplateAllowsLongRunningApiResponses() -> None:
    """The split-host edge proxy must tolerate cold local-model latency on packaged APIs."""
    templateText = Path(
        "/Users/hrudainirmal/Projects/Cortex/infra/nginx/edge.conf.template"
    ).read_text(encoding="utf-8")
    assert templateText.count("proxy_read_timeout 300s;") >= 2
    assert templateText.count("proxy_send_timeout 300s;") >= 2


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
                "Origin": "https://cortex-app.client.internal",
                "Access-Control-Request-Method": "GET",
            },
        )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://cortex-app.client.internal"


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
async def testStartupHealthReportsDeploymentStartupPolicy() -> None:
    """Operators should be able to see whether the packaged API will fail closed on startup."""
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
    deploymentComponent = next(
        component
        for component in runtimeHealth.components
        if component.name == "deployment-config"
    )
    assert deploymentComponent.status == "ready"
    assert "startupPolicy=fail-closed" in deploymentComponent.detail
    assert "querySurfaceMode=bundled" in deploymentComponent.detail


@pytest.mark.asyncio
async def testStartupHealthReportsExternalQuerySurfaceMode() -> None:
    """Operators should be able to see when the employee chat shell is client-owned."""
    settings = buildPackageSettings(querySurfaceMode="external")
    runtimeHealth = await RuntimeHealthService(
        session=None,
        settings=settings,
        modelProvider=OllamaModelProvider(
            baseUrl=settings.ollamaBaseUrl,
            generatorModel=settings.generatorModel,
            embeddingModel=settings.embeddingModel,
        ),
    ).getStartupReadiness()
    deploymentComponent = next(
        component
        for component in runtimeHealth.components
        if component.name == "deployment-config"
    )
    assert deploymentComponent.status == "ready"
    assert "querySurfaceMode=external" in deploymentComponent.detail


@pytest.mark.asyncio
async def testStartupHealthReportsPackagedTorchBuildProfile() -> None:
    """Operators should be able to inspect the packaged Torch wheel channel at runtime."""
    settings = buildPackageSettings(
        packagePyTorchWheelIndexUrl="https://download.pytorch.org/whl/cpu",
        packagePyTorchPreinstall="torch torchvision",
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
    buildProfileComponent = next(
        component
        for component in runtimeHealth.components
        if component.name == "package-build-profile"
    )
    assert buildProfileComponent.status == "ready"
    assert "torchWheelIndex=https://download.pytorch.org/whl/cpu" in buildProfileComponent.detail
    assert "preinstall=torch torchvision" in buildProfileComponent.detail
    assert buildProfileComponent.remediation is not None


@pytest.mark.asyncio
async def testStartupHealthFlagsMismatchedPackagedTorchBuildProfile() -> None:
    """A CPU deployment profile should not advertise a CUDA-style packaged Torch channel."""
    settings = buildPackageSettings(
        packagePyTorchWheelIndexUrl="https://download.pytorch.org/whl/cu124",
        packagePyTorchPreinstall="torch torchvision",
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
    buildProfileComponent = next(
        component
        for component in runtimeHealth.components
        if component.name == "package-build-profile"
    )
    assert runtimeHealth.status == "degraded"
    assert buildProfileComponent.status == "degraded"
    assert buildProfileComponent.severity == "error"
    assert "torchWheelIndex=https://download.pytorch.org/whl/cu124" in buildProfileComponent.detail
    assert buildProfileComponent.remediation is not None


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
    assert identityComponent.severity == "warning"
    assert "authMode=fixture" in identityComponent.detail
    assert f"oidcIssuer={settings.oidcIssuerUrl}" in identityComponent.detail
    assert f"oidcAudience={settings.oidcAudience}" in identityComponent.detail
    assert identityComponent.remediation is not None
    assert "Fixture auth is suitable for packaged evaluation" in identityComponent.remediation


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
async def testStartupHealthFlagsObjectStorageProbeWriteFailures(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Read/write probe failures should surface as explicit storage readiness errors."""

    def raiseWriteFailure(self: Path, data: str, encoding: str | None = None) -> int:
        raise OSError("read-only file system")

    monkeypatch.setattr(Path, "write_text", raiseWriteFailure)
    settings = buildPackageSettings(objectStorageRoot=str(tmp_path / "object-storage"))
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
    assert "read-only file system" in storageComponent.detail
    assert storageComponent.remediation is not None


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
async def testExternalQueryContractDescriptorExposesStableReplacementUiMetadata() -> None:
    """Replacement chat shells should be able to discover the live v1 contract descriptor."""
    application = createApp(buildPackageSettings())

    async with AsyncClient(
        transport=ASGITransport(app=application),
        base_url="http://testserver",
    ) as client:
        response = await client.get("/v1/chat/contracts/v1")

    payload = response.json()
    assert response.status_code == 200
    assert payload["contractVersion"] == "v1"
    assert payload["endpointPath"] == "/v1/chat/completions"
    assert payload["method"] == "POST"
    assert payload["authentication"] == "bearer-token"
    assert payload["supportsStreaming"] is False
    assert payload["requestOptions"] == {
        "userMessageSelectionPolicy": "last-non-empty-user-message",
        "streamRequiredValue": False,
        "supportsCitationToggle": True,
    }
    assert payload["querySurfaceMode"] == "bundled"
    assert payload["bundledQueryUiAvailable"] is True
    assert payload["traceEventsPathTemplate"] == "/v1/query/{traceId}/events"
    assert payload["operatorConsolePath"] == "/developer"
    assert payload["requestSchemaPath"] == "/v1/chat/contracts/v1/schemas/request"
    assert payload["responseSchemaPath"] == "/v1/chat/contracts/v1/schemas/response"
    assert payload["responseHeaders"] == [
        "X-Cortex-Contract-Version",
        "X-Cortex-Trace-Id",
        "X-Cortex-Evidence-Status",
        "X-Cortex-Route",
        "X-Cortex-Abstained",
    ]
    assert payload["extensionFields"][0] == "contractVersion"
    assert payload["employeeSafeExtensionFields"] == [
        "contractVersion",
        "traceId",
        "route",
        "correctedQuery",
        "evidenceStatus",
        "abstained",
        "claims",
        "citations",
        "stages",
    ]
    assert payload["operatorOnlyExtensionFields"] == ["traceEventsPath"]
    assert payload["errorStatuses"] == [
        {
            "statusCode": 422,
            "code": "invalid_request",
            "retryable": False,
            "meaning": "The request shape violates the stable Cortex query facade, for example no usable user message or stream=true.",
        },
        {
            "statusCode": 403,
            "code": "forbidden_scope",
            "retryable": False,
            "meaning": "The authenticated identity is not allowed to access the requested enterprise scope or sources.",
        },
        {
            "statusCode": 503,
            "code": "provider_unavailable",
            "retryable": True,
            "meaning": "A required local provider such as the configured model endpoint was unavailable or timed out during deterministic execution.",
        },
        {
            "statusCode": 500,
            "code": "internal_error",
            "retryable": True,
            "meaning": "Cortex failed outside the expected validation, authorization, or provider error contract.",
        },
    ]
    assert payload["abstentionEvidenceStatuses"] == ["insufficient", "conflict"]
    assert "Do not send raw enterprise scope" in payload["notes"][1]


@pytest.mark.asyncio
async def testExternalQueryContractDescriptorReportsClientOwnedQueryShell() -> None:
    """Replacement UIs should be able to discover whether the bundled employee shell ships."""
    application = createApp(buildPackageSettings(querySurfaceMode="external"))

    async with AsyncClient(
        transport=ASGITransport(app=application),
        base_url="http://testserver",
    ) as client:
        response = await client.get("/v1/chat/contracts/v1")

    payload = response.json()
    assert response.status_code == 200
    assert payload["querySurfaceMode"] == "external"
    assert payload["bundledQueryUiAvailable"] is False


@pytest.mark.asyncio
async def testExternalQueryContractSchemaEndpointsExposeStableRequestAndResponseShapes() -> None:
    """Replacement chat shells should be able to fetch machine-readable request/response schemas."""
    application = createApp(buildPackageSettings())

    async with AsyncClient(
        transport=ASGITransport(app=application),
        base_url="http://testserver",
    ) as client:
        requestSchemaResponse = await client.get("/v1/chat/contracts/v1/schemas/request")
        responseSchemaResponse = await client.get("/v1/chat/contracts/v1/schemas/response")

    requestSchema = requestSchemaResponse.json()
    responseSchema = responseSchemaResponse.json()
    assert requestSchemaResponse.status_code == 200
    assert responseSchemaResponse.status_code == 200
    assert requestSchema["title"] == "ChatCompletionRequestSchema"
    assert "messages" in requestSchema["properties"]
    assert "cortex" in requestSchema["properties"]
    assert requestSchema["properties"]["stream"]["const"] is False
    assert responseSchema["title"] == "ChatCompletionResponseSchema"
    assert "x_cortex" in responseSchema["properties"]
    responseMetadataSchema = responseSchema["$defs"]["ExternalQueryMetadataSchema"]
    assert "claims" in responseMetadataSchema["properties"]
    assert "citations" in responseMetadataSchema["properties"]


@pytest.mark.asyncio
async def testWorkerStartupHealthEndpointExposesSharedOperatorContract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Operators should be able to inspect the shared worker-startup contract from the API."""
    application = createApp(buildPackageSettings())

    async def stubCollectWorkerStartupHealth(settings):
        return {
            "status": "blocked",
            "environment": settings.environment,
            "startupStatus": "ready",
            "liveReadinessStatus": "degraded",
            "blockingPhase": "live",
            "detail": (
                "worker startup blocked by runtime health checks: "
                "postgresql: database ready but pgvector extension is missing"
            ),
            "failingComponents": [
                {
                    "name": "postgresql",
                    "status": "degraded",
                    "severity": "error",
                    "detail": "database ready but pgvector extension is missing",
                    "remediation": "Install or enable the PostgreSQL vector extension.",
                }
            ],
        }

    monkeypatch.setattr(routeModule, "collectWorkerStartupHealth", stubCollectWorkerStartupHealth)

    async with AsyncClient(
        transport=ASGITransport(app=application),
        base_url="http://testserver",
    ) as client:
        response = await client.get("/health/worker-startup")

    payload = response.json()
    assert response.status_code == 200
    assert payload["status"] == "blocked"
    assert payload["blockingPhase"] == "live"
    assert payload["startupStatus"] == "ready"
    assert payload["liveReadinessStatus"] == "degraded"
    assert "worker startup blocked by runtime health checks" in payload["detail"]
    assert payload["failingComponents"][0]["name"] == "postgresql"
    assert "pgvector extension is missing" in payload["failingComponents"][0]["detail"]


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
async def testDevelopmentSeedEndpointSkipsSampleTraceGeneration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Packaged verification seeding should stay fast by skipping model-backed sample traces."""
    application = createApp(buildPackageSettings())

    class StubSession:
        """Provide the tiny session surface exercised by the seed endpoint."""

        async def commit(self) -> None:
            return None

    async def overrideDatabaseSession():
        yield StubSession()

    async def fakeSeedFixtures(session, settings, modelProvider, *, includeSampleTraces: bool = True):
        assert includeSampleTraces is False
        return SeedFixturesResponse(
            seededDocuments=9,
            enterprises=[settings.enterpriseId],
            traceCount=0,
        )

    async def fakePersistControlPlaneAudit(**_: object) -> None:
        return None

    application.dependency_overrides[getDatabaseSession] = overrideDatabaseSession
    monkeypatch.setattr(routeModule, "seedFixtures", fakeSeedFixtures)
    monkeypatch.setattr(routeModule, "persistControlPlaneAudit", fakePersistControlPlaneAudit)

    async with AsyncClient(
        transport=ASGITransport(app=application),
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            "/v1/dev/seed",
            headers={"Authorization": "Bearer fixture-admin"},
        )

    payload = response.json()
    assert response.status_code == 200
    assert payload["seededDocuments"] == 9
    assert payload["traceCount"] == 0


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
    assert response.headers["x-cortex-route"] == "rag"
    assert response.headers["x-cortex-abstained"] == "false"
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
async def testExternalChatContractSurfacesProviderFailuresAsServiceUnavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Replacement query shells should receive retryable transport semantics for model timeouts."""
    application = createApp(buildPackageSettings())

    async def overrideDatabaseSession():
        yield object()

    class StubQueryService:
        """Raise one provider failure without depending on the live model endpoint."""

        def __init__(self, session, settings, modelProvider) -> None:
            self.session = session

        async def answerQuery(self, request) -> QueryResponse:
            raise ProviderOperationError("bounded generation request failed")

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
                "messages": [{"role": "user", "content": "What are our retention rules?"}],
                "stream": False,
                "cortex": {"showCitations": True},
            },
        )

    assert response.status_code == 503
    assert response.json()["detail"] == "bounded generation request failed"


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
    assert response.headers["x-cortex-route"] == "rag"
    assert response.headers["x-cortex-abstained"] == "true"
    assert payload["x_cortex"]["abstained"] is True
    assert payload["x_cortex"]["claims"][0]["supportStatus"] == "conflict"
    assert payload["x_cortex"]["citations"][0]["documentTitle"] == "Security Handbook"
    assert payload["x_cortex"]["traceEventsPath"] == "/v1/query/8b24db0b-bccd-4b45-9073-60c35fd8347b/events"

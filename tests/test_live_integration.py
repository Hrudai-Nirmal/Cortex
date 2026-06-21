"""Live integration tests cover PostgreSQL persistence, local model IO, and worker flows."""

from __future__ import annotations

import asyncio
import json
import threading
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import asyncpg
import cortex.api.routes as routeModule
import pytest
from alembic import command
from alembic.config import Config
from cortex.config import Settings
from cortex.database import getDatabaseSession
from cortex.errors import ProviderOperationError
from cortex.main import createApp
from cortex.schemas import (
    AccessScopeSchema,
    CreateWebsiteSourceRequest,
    IngestTextRequest,
    QueryRequest,
)
from cortex.services.jobs import DurableJobService
from cortex.services.model_provider import OllamaModelProvider, buildDeterministicEmbedding
from cortex.services.object_storage import LocalObjectStorage
from cortex.services.query import QueryService
from cortex.services.retention import purgeExpiredTraces
from cortex.services.runtime import RuntimeHealthService
from cortex.services.seed import seedFixtures
from cortex.services.sources import SourceService
from cortex.worker import processNextJob
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

TEST_DATABASE_URL = "postgresql+asyncpg://cortex:cortex@127.0.0.1:5432/cortex_live_tests"


class LocalModelHandler(BaseHTTPRequestHandler):
    """Serve deterministic embedding and generation responses over a local HTTP port."""

    generatorModel = "qwen3:14b"
    embeddingModel = "qwen3-embedding:0.6b"

    def do_GET(self) -> None:  # noqa: N802
        if self.path != "/api/tags":
            self.send_error(404)
            return
        self._sendJson(
            {
                "models": [
                    {"name": self.generatorModel},
                    {"name": self.embeddingModel},
                ]
            }
        )

    def do_POST(self) -> None:  # noqa: N802
        payload = self._readPayload()
        if self.path == "/v1/embeddings":
            inputs = payload.get("input", [])
            self._sendJson(
                {
                    "data": [
                        {"embedding": buildDeterministicEmbedding(textValue)}
                        for textValue in inputs
                    ]
                }
            )
            return
        if self.path == "/v1/chat/completions":
            userContent = payload["messages"][1]["content"]
            claims = []
            for block in userContent.split("\n\n"):
                blockLines = block.splitlines()
                chunkId = next(
                    (
                        line.split(": ", maxsplit=1)[1]
                        for line in blockLines
                        if line.startswith("chunk_id: ")
                    ),
                    None,
                )
                content = next(
                    (
                        line.split(": ", maxsplit=1)[1]
                        for line in blockLines
                        if line.startswith("content: ")
                    ),
                    None,
                )
                if chunkId and content:
                    claims.append({"chunkId": chunkId, "text": content})
                if len(claims) == 2:
                    break
            self._sendJson({"choices": [{"message": {"content": json.dumps({"claims": claims})}}]})
            return
        self.send_error(404)

    def log_message(self, format: str, *args: object) -> None:
        return

    def _readPayload(self) -> dict[str, Any]:
        contentLength = int(self.headers.get("Content-Length", "0"))
        rawPayload = self.rfile.read(contentLength)
        return json.loads(rawPayload.decode("utf-8")) if rawPayload else {}

    def _sendJson(self, payload: dict[str, Any]) -> None:
        responseBody = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(responseBody)))
        self.end_headers()
        self.wfile.write(responseBody)


class WebsiteFixtureHandler(BaseHTTPRequestHandler):
    """Serve one deterministic allowlisted HTML page for website-ingestion tests."""

    def do_GET(self) -> None:  # noqa: N802
        if self.path != "/policy":
            self.send_error(404)
            return
        responseBody = b"""
        <html>
          <body>
            <h1>Support Policy</h1>
            <p>Escalations must be acknowledged within 24 hours.</p>
          </body>
        </html>
        """
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(responseBody)))
        self.end_headers()
        self.wfile.write(responseBody)

    def log_message(self, format: str, *args: object) -> None:
        return


@pytest.fixture(scope="session")
def localModelServer() -> str:
    """Start a deterministic local model endpoint matching the Ollama-compatible contract."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), LocalModelHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join(timeout=5)


@pytest.fixture(scope="session")
def localWebsiteServer() -> str:
    """Start a deterministic local HTML server for allowlisted website ingestion tests."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), WebsiteFixtureHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/policy"
    finally:
        server.shutdown()
        thread.join(timeout=5)


@pytest.fixture(scope="session")
async def liveDatabaseUrl() -> str:
    """Provision a dedicated PostgreSQL database for integration tests when available."""
    parsedUrl = urlparse(TEST_DATABASE_URL.replace("+asyncpg", ""))
    adminUrl = parsedUrl._replace(path="/postgres").geturl()
    try:
        connection = await asyncpg.connect(adminUrl)
    except Exception as error:
        pytest.skip(f"live PostgreSQL is unavailable: {error}")
    try:
        databaseName = parsedUrl.path.lstrip("/")
        exists = await connection.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1",
            databaseName,
        )
        if not exists:
            await connection.execute(f'CREATE DATABASE "{databaseName}"')
    finally:
        await connection.close()
    yield TEST_DATABASE_URL


@pytest.fixture()
def sessionFactory(liveDatabaseUrl: str):
    """Apply migrations to the dedicated test database and expose an async session factory."""
    alembicConfig = Config(str(Path("alembic.ini").resolve()))
    alembicConfig.set_main_option("sqlalchemy.url", liveDatabaseUrl)
    command.upgrade(alembicConfig, "head")
    engine = create_async_engine(liveDatabaseUrl, pool_pre_ping=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        asyncio.run(engine.dispose())


@pytest.fixture()
async def databaseSession(sessionFactory) -> AsyncSession:
    """Truncate integration tables so every live test starts from a known state."""
    async with sessionFactory() as session:
        await session.execute(
            text(
                """
                TRUNCATE TABLE
                    durable_job,
                    audit_log,
                    trace_memory,
                    chunk_acl,
                    chunk,
                    document_version,
                    document,
                    source_blob,
                    enterprise
                CASCADE
                """
            )
        )
        await session.commit()
        yield session


def buildSettings(
    localModelBaseUrl: str,
    liveDatabaseUrl: str,
    websiteAllowlist: tuple[str, ...] = ("127.0.0.1", "localhost"),
) -> Settings:
    """Create test settings without reading from a developer's ambient environment."""
    return Settings(
        environment="test",
        databaseUrl=liveDatabaseUrl,
        devMode=False,
        requiredAccelerator="cpu",
        ollamaBaseUrl=localModelBaseUrl,
        objectStorageRoot=".cortex-data/test-object-storage",
        generatorModel="qwen3:14b",
        embeddingModel="qwen3-embedding:0.6b",
        websiteAllowlist=websiteAllowlist,
    )


@pytest.mark.asyncio
async def testLiveSeedAndScopedQuery(
    databaseSession: AsyncSession,
    liveDatabaseUrl: str,
    localModelServer: str,
) -> None:
    """Seeded queries must stay inside scope, correct spelling, and persist traces."""
    settings = buildSettings(localModelServer, liveDatabaseUrl)
    modelProvider = OllamaModelProvider(
        baseUrl=settings.ollamaBaseUrl,
        generatorModel=settings.generatorModel,
        embeddingModel=settings.embeddingModel,
    )
    seedResult = await seedFixtures(databaseSession, settings, modelProvider)

    queryService = QueryService(databaseSession, settings, modelProvider)
    retentionResponse = await queryService.answerQuery(
        QueryRequest(
            query="What are our retentin rules?",
            accessScope=AccessScopeSchema(
                enterpriseId=settings.enterpriseId,
                actorId="maya.chen@example.com",
                principalIds=["group:employees"],
            ),
        )
    )
    restrictedResponse = await queryService.answerQuery(
        QueryRequest(
            query="What must pass before a pipeline is promoted?",
            accessScope=AccessScopeSchema(
                enterpriseId=settings.enterpriseId,
                actorId="maya.chen@example.com",
                principalIds=["group:employees"],
            ),
        )
    )

    latestTrace = await queryService.getLatestTrace(settings.enterpriseId)

    assert seedResult.seededDocuments >= 8
    assert retentionResponse.correctedQuery is not None
    assert "30 days" in retentionResponse.answer
    assert restrictedResponse.evidenceStatus in {"insufficient", "conflict"}
    assert all(
        citation.documentTitle != "Pipeline Promotion Policy"
        for citation in restrictedResponse.citations
    )
    assert latestTrace is not None
    assert len(latestTrace.stages) >= 4


@pytest.mark.asyncio
async def testTracePurgePreservesAuditRecordLive(
    databaseSession: AsyncSession,
    liveDatabaseUrl: str,
    localModelServer: str,
) -> None:
    """Purging raw traces must leave the content-free audit record intact and correlated."""
    settings = buildSettings(localModelServer, liveDatabaseUrl)
    modelProvider = OllamaModelProvider(
        baseUrl=settings.ollamaBaseUrl,
        generatorModel=settings.generatorModel,
        embeddingModel=settings.embeddingModel,
    )
    await seedFixtures(databaseSession, settings, modelProvider)

    await purgeExpiredTraces(databaseSession, datetime.now(UTC) + timedelta(days=365))

    traceCount = await databaseSession.scalar(text("SELECT count(*) FROM trace_memory"))
    auditRow = (
        (
            await databaseSession.execute(
                text(
                    """
                SELECT trace_memory_id, trace_identifier_hash, event_payload
                FROM audit_log
                ORDER BY created_at DESC
                LIMIT 1
                """
                )
            )
        )
        .mappings()
        .one()
    )

    assert int(traceCount or 0) == 0
    assert auditRow["trace_memory_id"] is None
    assert bytes(auditRow["trace_identifier_hash"])
    assert "raw_query" not in json.dumps(auditRow["event_payload"])


@pytest.mark.asyncio
async def testWorkerProcessesQueuedIngestionJobLive(
    databaseSession: AsyncSession,
    liveDatabaseUrl: str,
    localModelServer: str,
) -> None:
    """The durable worker should execute queued ingestion jobs into the live database."""
    settings = buildSettings(localModelServer, liveDatabaseUrl)
    jobService = DurableJobService(databaseSession)
    jobId = await jobService.enqueueIngestionJob(
        IngestTextRequest(
            enterpriseId=settings.enterpriseId,
            documentId="30000000-0000-0000-0000-000000000001",
            documentTitle="Queued Worker Document",
            sourceUri="seed://queued-worker-document",
            versionLabel="1.0",
            content="The queued worker document contains approved queue processing evidence.",
            principalIds=["group:employees"],
        )
    )

    await processNextJob(databaseSession, settings)

    jobStatus = await databaseSession.scalar(
        text("SELECT status FROM durable_job WHERE id = :job_id"),
        {"job_id": jobId},
    )
    chunkCount = await databaseSession.scalar(text("SELECT count(*) FROM chunk"))
    runtimeHealth = await RuntimeHealthService(
        session=databaseSession,
        settings=settings,
        modelProvider=OllamaModelProvider(
            baseUrl=settings.ollamaBaseUrl,
            generatorModel=settings.generatorModel,
            embeddingModel=settings.embeddingModel,
        ),
    ).getReadiness()

    assert jobStatus == "completed"
    assert int(chunkCount or 0) > 0
    assert runtimeHealth.status in {"ready", "degraded"}


@pytest.mark.asyncio
async def testUploadSourceQueuesAndProcessesLive(
    databaseSession: AsyncSession,
    liveDatabaseUrl: str,
    localModelServer: str,
) -> None:
    """Uploaded sources should persist one blob, queue one deterministic job, and activate once."""
    settings = buildSettings(localModelServer, liveDatabaseUrl)
    sourceService = SourceService(
        session=databaseSession,
        settings=settings,
        objectStorage=LocalObjectStorage(Path(settings.objectStorageRoot)),
    )

    firstResponse = await sourceService.createUploadSource(
        enterpriseId=settings.enterpriseId,
        actorId="alex.rivera@example.com",
        displayName="Operations Handbook",
        versionLabel="1.0",
        principalIds=["group:employees"],
        fileName="operations-handbook.txt",
        mimeType="text/plain",
        content=b"Approved handbook evidence for employees only.",
    )
    secondResponse = await sourceService.createUploadSource(
        enterpriseId=settings.enterpriseId,
        actorId="alex.rivera@example.com",
        displayName="Operations Handbook",
        versionLabel="1.0",
        principalIds=["group:employees"],
        fileName="operations-handbook.txt",
        mimeType="text/plain",
        content=b"Approved handbook evidence for employees only.",
        documentId=firstResponse.documentId,
    )

    await processNextJob(databaseSession, settings)

    versionRow = (
        (
            await databaseSession.execute(
                text(
                    """
                    SELECT status, ingestion_status
                    FROM document_version
                    WHERE id = :version_id
                    """
                ),
                {"version_id": firstResponse.documentVersionId},
            )
        )
        .mappings()
        .one()
    )
    jobCount = await databaseSession.scalar(text("SELECT count(*) FROM durable_job"))
    blobCount = await databaseSession.scalar(text("SELECT count(*) FROM source_blob"))
    chunkCount = await databaseSession.scalar(text("SELECT count(*) FROM chunk"))

    assert firstResponse.jobId == secondResponse.jobId
    assert versionRow["status"] == "active"
    assert versionRow["ingestion_status"] == "active"
    assert int(jobCount or 0) == 1
    assert int(blobCount or 0) == 1
    assert int(chunkCount or 0) > 0


@pytest.mark.asyncio
async def testWebsiteSourcePersistsAllowlistedSnapshotLive(
    databaseSession: AsyncSession,
    liveDatabaseUrl: str,
    localModelServer: str,
    localWebsiteServer: str,
) -> None:
    """Allowlisted single-page websites should persist a snapshot and activate as source content."""
    settings = buildSettings(localModelServer, liveDatabaseUrl, websiteAllowlist=("127.0.0.1",))
    sourceService = SourceService(
        session=databaseSession,
        settings=settings,
        objectStorage=LocalObjectStorage(Path(settings.objectStorageRoot)),
    )

    response = await sourceService.createWebsiteSource(
        CreateWebsiteSourceRequest(
            displayName="Support Policy",
            enterpriseId=settings.enterpriseId,
            principalIds=["group:employees"],
            sourceUri=localWebsiteServer,
            versionLabel="2026.06",
            sourceAuthority=0.91,
            extractionQuality=0.9,
            metadata={},
        ),
        actorId="alex.rivera@example.com",
    )

    await processNextJob(databaseSession, settings)

    sourceRow = (
        (
            await databaseSession.execute(
                text(
                    """
                    SELECT d.source_type, dv.mime_type, dv.status
                    FROM document AS d
                    JOIN document_version AS dv ON dv.document_id = d.id
                    WHERE d.id = :document_id
                    """
                ),
                {"document_id": response.documentId},
            )
        )
        .mappings()
        .one()
    )

    assert sourceRow["source_type"] == "website"
    assert sourceRow["mime_type"] == "text/html"
    assert sourceRow["status"] == "active"


@pytest.mark.asyncio
async def testFailedSourceStaysQuarantinedAndOutOfRetrievalLive(
    databaseSession: AsyncSession,
    liveDatabaseUrl: str,
    localModelServer: str,
) -> None:
    """A parse failure must quarantine the version, fail the job, and leave retrieval empty."""
    settings = buildSettings(localModelServer, liveDatabaseUrl)
    sourceService = SourceService(
        session=databaseSession,
        settings=settings,
        objectStorage=LocalObjectStorage(Path(settings.objectStorageRoot)),
    )

    response = await sourceService.createUploadSource(
        enterpriseId=settings.enterpriseId,
        actorId="alex.rivera@example.com",
        displayName="Broken CSV",
        versionLabel="1.0",
        principalIds=["group:employees"],
        fileName="broken.csv",
        mimeType="text/csv",
        content=b"\xff\xfe\x00\x00",
    )

    with pytest.raises(ProviderOperationError):
        await processNextJob(databaseSession, settings)

    versionRow = (
        (
            await databaseSession.execute(
                text(
                    """
                    SELECT status, ingestion_status, quarantine_status, failure_code
                    FROM document_version
                    WHERE id = :version_id
                    """
                ),
                {"version_id": response.documentVersionId},
            )
        )
        .mappings()
        .one()
    )
    chunkCount = await databaseSession.scalar(
        text(
            """
            SELECT count(*)
            FROM chunk
            WHERE document_version_id = :version_id
            """
        ),
        {"version_id": response.documentVersionId},
    )

    assert versionRow["status"] == "failed"
    assert versionRow["ingestion_status"] == "failed"
    assert versionRow["quarantine_status"] == "quarantined"
    assert versionRow["failure_code"] in {"SOURCE_PARSE_FAILED", "INGESTION_FAILED"}
    assert int(chunkCount or 0) == 0


@pytest.mark.asyncio
async def testDeveloperSourceMutationRequiresAdminAndAuditsDenialLive(
    databaseSession: AsyncSession,
    liveDatabaseUrl: str,
    localModelServer: str,
    localWebsiteServer: str,
) -> None:
    """Builder identities must not be able to mutate source onboarding state."""
    settings = buildSettings(localModelServer, liveDatabaseUrl, websiteAllowlist=("127.0.0.1",))
    routeModule.settings = settings
    application = createApp()

    async def overrideDatabaseSession():
        yield databaseSession

    application.dependency_overrides[getDatabaseSession] = overrideDatabaseSession

    async with AsyncClient(
        transport=ASGITransport(app=application),
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            "/v1/sources/website",
            headers={"Authorization": "Bearer fixture-builder"},
            json={
                "displayName": "Support Policy",
                "enterpriseId": str(settings.enterpriseId),
                "principalIds": ["group:employees"],
                "sourceUri": localWebsiteServer,
                "versionLabel": "2026.06",
                "sourceAuthority": 0.91,
                "extractionQuality": 0.9,
                "metadata": {},
            },
        )

    auditRow = (
        (
            await databaseSession.execute(
                text(
                    """
                    SELECT actor_id, action, outcome, event_payload
                    FROM audit_log
                    WHERE action = 'source.website.create'
                    ORDER BY created_at DESC
                    LIMIT 1
                    """
                )
            )
        )
        .mappings()
        .one()
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "admin role required"
    assert auditRow["actor_id"] == "riley.patel@example.com"
    assert auditRow["outcome"] == "denied"
    assert auditRow["event_payload"]["reason"] == "admin role required"


@pytest.mark.asyncio
async def testPipelineLifecyclePersistsAndAuditsLive(
    databaseSession: AsyncSession,
    liveDatabaseUrl: str,
    localModelServer: str,
) -> None:
    """Active, validated, and activated pipeline versions should persist with audit evidence."""
    settings = buildSettings(localModelServer, liveDatabaseUrl)
    routeModule.settings = settings
    application = createApp()

    async def overrideDatabaseSession():
        yield databaseSession

    application.dependency_overrides[getDatabaseSession] = overrideDatabaseSession

    async with AsyncClient(
        transport=ASGITransport(app=application),
        base_url="http://testserver",
    ) as client:
        sessionResponse = await client.get(
            "/v1/session",
            headers={"Authorization": "Bearer fixture-admin"},
        )
        activeResponse = await client.get(
            f"/v1/pipelines/active?enterpriseId={settings.enterpriseId}",
            headers={"Authorization": "Bearer fixture-admin"},
        )
        validateResponse = await client.post(
            "/v1/pipelines/validate",
            headers={"Authorization": "Bearer fixture-admin"},
            json={"enterpriseId": str(settings.enterpriseId)},
        )
        activateResponse = await client.post(
            "/v1/pipelines/activate",
            headers={"Authorization": "Bearer fixture-admin"},
            json={"enterpriseId": str(settings.enterpriseId)},
        )
        versionsResponse = await client.get(
            f"/v1/pipelines/versions?enterpriseId={settings.enterpriseId}",
            headers={"Authorization": "Bearer fixture-admin"},
        )

    versionsPayload = versionsResponse.json()
    auditActions = (
        (
            await databaseSession.execute(
                text(
                    """
                    SELECT action, outcome
                    FROM audit_log
                    WHERE action LIKE 'pipeline.%'
                    ORDER BY created_at ASC
                    """
                )
            )
        )
        .mappings()
        .all()
    )

    assert sessionResponse.status_code == 200
    assert sessionResponse.json()["actorId"] == "alex.rivera@example.com"
    assert activeResponse.status_code == 200
    assert activeResponse.json()["status"] == "active"
    assert validateResponse.status_code == 200
    assert validateResponse.json()["status"] == "active"
    assert activateResponse.status_code == 200
    assert activateResponse.json()["status"] == "active"
    assert versionsResponse.status_code == 200
    assert [version["status"] for version in versionsPayload] == ["active"]
    assert [(row["action"], row["outcome"]) for row in auditActions] == [
        ("pipeline.bootstrap", "active"),
        ("pipeline.validate", "active"),
        ("pipeline.activate", "active"),
    ]


@pytest.mark.asyncio
async def testOpenAiCompatibleChatFacadeUsesAuthenticatedScopeLive(
    databaseSession: AsyncSession,
    liveDatabaseUrl: str,
    localModelServer: str,
) -> None:
    """Client-owned chat shells should integrate without sending raw access-scope payloads."""
    settings = buildSettings(localModelServer, liveDatabaseUrl)
    await seedFixtures(
        databaseSession,
        settings,
        OllamaModelProvider(
            baseUrl=settings.ollamaBaseUrl,
            generatorModel=settings.generatorModel,
            embeddingModel=settings.embeddingModel,
        ),
    )
    routeModule.settings = settings
    application = createApp(settings)

    async def overrideDatabaseSession():
        yield databaseSession

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
                "messages": [{"role": "user", "content": "What are our retentin rules?"}],
                "stream": False,
                "cortex": {"showCitations": True},
            },
        )

    payload = response.json()
    assert response.status_code == 200
    assert payload["object"] == "chat.completion"
    assert payload["choices"][0]["message"]["content"]
    assert payload["x_cortex"]["traceId"]
    assert payload["x_cortex"]["evidenceStatus"] in {
        "sufficient",
        "partial",
        "insufficient",
        "conflict",
    }
    assert payload["x_cortex"]["citations"]


@pytest.mark.asyncio
async def testTraceRoutesRequireBuilderIdentityLive(
    databaseSession: AsyncSession,
    liveDatabaseUrl: str,
    localModelServer: str,
) -> None:
    """Employee identities must not be allowed to inspect developer trace surfaces."""
    settings = buildSettings(localModelServer, liveDatabaseUrl)
    modelProvider = OllamaModelProvider(
        baseUrl=settings.ollamaBaseUrl,
        generatorModel=settings.generatorModel,
        embeddingModel=settings.embeddingModel,
    )
    await seedFixtures(databaseSession, settings, modelProvider)
    latestTraceId = await databaseSession.scalar(
        text("SELECT id FROM trace_memory ORDER BY created_at DESC LIMIT 1")
    )
    assert latestTraceId is not None

    routeModule.settings = settings
    application = createApp()

    async def overrideDatabaseSession():
        yield databaseSession

    application.dependency_overrides[getDatabaseSession] = overrideDatabaseSession

    async with AsyncClient(
        transport=ASGITransport(app=application),
        base_url="http://testserver",
    ) as client:
        latestResponse = await client.get(
            f"/v1/traces/latest?enterpriseId={settings.enterpriseId}",
            headers={"Authorization": "Bearer fixture-employee"},
        )
        traceResponse = await client.get(
            f"/v1/traces/{latestTraceId}",
            headers={"Authorization": "Bearer fixture-employee"},
        )

    deniedActions = (
        (
            await databaseSession.execute(
                text(
                    """
                    SELECT action, outcome
                    FROM audit_log
                    WHERE outcome = 'denied'
                    ORDER BY created_at ASC
                    """
                )
            )
        )
        .mappings()
        .all()
    )

    assert latestResponse.status_code == 403
    assert traceResponse.status_code == 403
    assert {(row["action"], row["outcome"]) for row in deniedActions} >= {
        ("trace.latest.read", "denied"),
        ("trace.detail.read", "denied"),
    }

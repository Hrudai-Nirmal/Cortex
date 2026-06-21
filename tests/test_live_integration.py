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
import pytest
from alembic import command
from alembic.config import Config
from cortex.config import Settings
from cortex.schemas import AccessScopeSchema, IngestTextRequest, QueryRequest
from cortex.services.jobs import DurableJobService
from cortex.services.model_provider import OllamaModelProvider, buildDeterministicEmbedding
from cortex.services.query import QueryService
from cortex.services.retention import purgeExpiredTraces
from cortex.services.runtime import RuntimeHealthService
from cortex.services.seed import seedFixtures
from cortex.worker import processNextJob
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
                    enterprise
                CASCADE
                """
            )
        )
        await session.commit()
        yield session


def buildSettings(localModelBaseUrl: str, liveDatabaseUrl: str) -> Settings:
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

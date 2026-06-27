"""Versioned API routes for the executable Cortex live integration baseline."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from cortex.config import Settings, getSettings
from cortex.database import getDatabaseSession
from cortex.domain.chunking import ChunkerConfig
from cortex.errors import AuthorizationScopeError, CortexError, InputValidationError, ProviderOperationError
from cortex.schemas import (
    ActivatePipelineRequest,
    ChatCompletionRequestSchema,
    ChatCompletionResponseSchema,
    CreateUploadSourceResponse,
    CreateWebsiteSourceRequest,
    CreateWebsiteSourceResponse,
    ExternalQueryContractDescriptorSchema,
    IngestTextRequest,
    IngestTextResponse,
    JobStatusResponse,
    JobSummaryResponse,
    PipelineGraphResponse,
    PipelineVersionSummaryResponse,
    QueryRequest,
    QueryResponse,
    QueuedJobResponse,
    RuntimeHealthResponse,
    SeedFixturesResponse,
    SessionResponse,
    SourceDetailResponse,
    SourceSummaryResponse,
    TraceSummaryResponse,
    ValidatePipelineRequest,
)
from cortex.services.audit import persistControlPlaneAudit
from cortex.services.auth import requireAdminIdentity, requireBuilderIdentity, resolveIdentity
from cortex.services.ingestion import IngestionService, PostgresIngestionRepository
from cortex.services.jobs import DurableJobService
from cortex.services.model_provider import OllamaModelProvider
from cortex.services.object_storage import LocalObjectStorage
from cortex.services.pipelines import PipelineService
from cortex.services.query import QueryService
from cortex.services.runtime import RuntimeHealthService
from cortex.services.seed import seedFixtures
from cortex.services.sources import SourceService

router = APIRouter()
settings = getSettings()
DatabaseSession = Annotated[AsyncSession, Depends(getDatabaseSession)]
EXTERNAL_QUERY_CONTRACT_RESPONSE_HEADERS = [
    "X-Cortex-Contract-Version",
    "X-Cortex-Trace-Id",
    "X-Cortex-Evidence-Status",
    "X-Cortex-Route",
    "X-Cortex-Abstained",
]
EXTERNAL_QUERY_CONTRACT_EXTENSION_FIELDS = [
    "contractVersion",
    "traceId",
    "traceEventsPath",
    "route",
    "correctedQuery",
    "evidenceStatus",
    "abstained",
    "claims",
    "citations",
    "stages",
]
EXTERNAL_QUERY_EMPLOYEE_SAFE_EXTENSION_FIELDS = [
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
EXTERNAL_QUERY_OPERATOR_ONLY_EXTENSION_FIELDS = ["traceEventsPath"]
EXTERNAL_QUERY_ERROR_STATUSES = [
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
EXTERNAL_QUERY_CONTRACT_NOTES = [
    "Use the last non-empty user message as the deterministic query input.",
    "Do not send raw enterprise scope or ACL principals from the browser; Cortex derives them from the bearer token.",
    "Treat traceEventsPath as an operator-grade debugging surface rather than a standard employee UI dependency.",
]


def buildModelProvider(activeSettings: Settings) -> OllamaModelProvider:
    """Create the configured local model provider for request-scoped services."""
    return OllamaModelProvider(
        baseUrl=activeSettings.ollamaBaseUrl,
        generatorModel=activeSettings.generatorModel,
        embeddingModel=activeSettings.embeddingModel,
    )


def buildSourceService(session: AsyncSession) -> SourceService:
    """Create the live source operations service backed by local object storage."""
    return SourceService(
        session=session,
        settings=settings,
        objectStorage=LocalObjectStorage(Path(settings.objectStorageRoot)),
    )


def mapCortexErrorToHttp(error: CortexError) -> HTTPException:
    """Preserve domain failure meaning at the HTTP contract boundary."""
    if isinstance(error, InputValidationError):
        return HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(error),
        )
    if isinstance(error, AuthorizationScopeError):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error))
    if isinstance(error, ProviderOperationError):
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(error),
        )
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error))


def buildPipelineService(session: AsyncSession) -> PipelineService:
    """Create the persisted pipeline governance service for the active enterprise."""
    return PipelineService(session=session, settings=settings)


def buildExternalQueryContractDescriptor() -> ExternalQueryContractDescriptorSchema:
    """Return the stable live contract exported to replacement employee chat shells."""
    return ExternalQueryContractDescriptorSchema(
        contractVersion="v1",
        endpointPath="/v1/chat/completions",
        method="POST",
        authentication="bearer-token",
        supportsStreaming=False,
        requestOptions={
            "userMessageSelectionPolicy": "last-non-empty-user-message",
            "streamRequiredValue": False,
            "supportsCitationToggle": True,
        },
        querySurfaceMode=settings.querySurfaceMode,
        bundledQueryUiAvailable=settings.querySurfaceMode == "bundled",
        traceEventsPathTemplate="/v1/query/{traceId}/events",
        operatorConsolePath="/developer",
        responseHeaders=EXTERNAL_QUERY_CONTRACT_RESPONSE_HEADERS,
        extensionFields=EXTERNAL_QUERY_CONTRACT_EXTENSION_FIELDS,
        employeeSafeExtensionFields=EXTERNAL_QUERY_EMPLOYEE_SAFE_EXTENSION_FIELDS,
        operatorOnlyExtensionFields=EXTERNAL_QUERY_OPERATOR_ONLY_EXTENSION_FIELDS,
        errorStatuses=EXTERNAL_QUERY_ERROR_STATUSES,
        evidenceStatuses=["sufficient", "partial", "insufficient", "conflict"],
        routes=["rag", "compute", "retrieve-then-compute"],
        abstentionEvidenceStatuses=["insufficient", "conflict"],
        notes=EXTERNAL_QUERY_CONTRACT_NOTES,
    )


@router.get("/health/live")
async def getLiveness() -> dict[str, str]:
    """Report process liveness without touching external dependencies."""
    return {"status": "live"}


@router.get("/health/ready", response_model=RuntimeHealthResponse)
async def getReadiness(session: DatabaseSession) -> RuntimeHealthResponse:
    """Report actual runtime readiness across the live local stack components."""
    runtimeHealthService = RuntimeHealthService(
        session=session,
        settings=settings,
        modelProvider=buildModelProvider(settings),
    )
    return await runtimeHealthService.getReadiness()


@router.get("/health/startup", response_model=RuntimeHealthResponse)
async def getStartupReadiness() -> RuntimeHealthResponse:
    """Report startup-safe deployment checks without hitting database or model endpoints."""
    runtimeHealthService = RuntimeHealthService(
        session=None,
        settings=settings,
        modelProvider=buildModelProvider(settings),
    )
    return await runtimeHealthService.getStartupReadiness()


@router.get("/v1/session", response_model=SessionResponse)
async def getSession(request: Request) -> SessionResponse:
    """Resolve the authenticated fixture or OIDC identity for the current browser surface."""
    identity = await resolveIdentity(request, settings)
    return SessionResponse(
        enterpriseId=identity.enterpriseId,
        actorId=identity.actorId,
        subject=identity.subject,
        email=identity.email,
        displayName=identity.displayName,
        groups=list(identity.groups),
        roles=list(identity.roles),
        principalIds=list(identity.principalIds),
        isAdmin=identity.isAdmin,
        isBuilder=identity.isBuilder,
    )


@router.get(
    "/v1/chat/contracts/v1",
    response_model=ExternalQueryContractDescriptorSchema,
)
async def getExternalQueryContract() -> ExternalQueryContractDescriptorSchema:
    """Publish the live stable query-facade contract for replacement client UIs."""
    return buildExternalQueryContractDescriptor()


@router.post("/v1/ingestion/text", response_model=IngestTextResponse)
async def ingestText(
    request: IngestTextRequest,
    session: DatabaseSession,
) -> IngestTextResponse:
    """Ingest text through deterministic chunking, embeddings, and idempotent activation."""
    try:
        ingestionService = IngestionService(
            repository=PostgresIngestionRepository(session),
            embeddingProvider=buildModelProvider(settings),
        )
        ingestionResult = await ingestionService.ingestText(
            enterpriseId=request.enterpriseId,
            documentId=request.documentId,
            documentTitle=request.documentTitle,
            versionLabel=request.versionLabel,
            content=request.content,
            config=ChunkerConfig(size=request.chunkSize, overlap=request.chunkOverlap),
            sourceUri=request.sourceUri,
            principalIds=tuple(request.principalIds),
            sourceAuthority=request.sourceAuthority,
            extractionQuality=request.extractionQuality,
            publishedAt=parseOptionalTimestamp(request.publishedAt),
            metadata=request.metadata,
        )
    except CortexError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)
        ) from error
    except Exception as error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="ingestion failed"
        ) from error
    return IngestTextResponse(
        documentVersionId=ingestionResult.documentVersionId,
        documentVersionHash=ingestionResult.documentVersionHash,
        chunkCount=ingestionResult.chunkCount,
        chunkIds=list(ingestionResult.chunkIds),
        status=ingestionResult.status,
    )


@router.post("/v1/ingestion/jobs/text", response_model=QueuedJobResponse)
async def enqueueTextIngestionJob(
    request: IngestTextRequest,
    session: DatabaseSession,
) -> QueuedJobResponse:
    """Queue ingestion for the durable worker instead of processing inline."""
    try:
        jobService = DurableJobService(session)
        jobId = await jobService.enqueueIngestionJob(request)
    except CortexError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)
        ) from error
    except Exception as error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="job enqueue failed"
        ) from error
    return QueuedJobResponse(jobId=jobId, status="queued")


@router.post("/v1/sources/uploads", response_model=CreateUploadSourceResponse)
async def createUploadSource(
    request: Request,
    enterpriseId: Annotated[UUID, Form()],
    displayName: Annotated[str, Form()],
    versionLabel: Annotated[str, Form()],
    principalIds: Annotated[str, Form()],
    file: Annotated[UploadFile, File()],
    session: DatabaseSession,
    documentId: Annotated[UUID | None, Form()] = None,
    sourceAuthority: Annotated[float, Form()] = 0.85,
    extractionQuality: Annotated[float, Form()] = 0.9,
    publishedAt: Annotated[str | None, Form()] = None,
    metadata: Annotated[str | None, Form()] = None,
) -> CreateUploadSourceResponse:
    """Accept a file upload, store it once by hash, and queue deterministic ingestion."""
    identity = await requireAdminIdentity(
        request=request,
        session=session,
        settings=settings,
        action="source.upload.create",
        enterpriseId=enterpriseId,
    )
    if file.content_type is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="uploaded file is missing its content type",
        )
    try:
        rawContent = await file.read()
        sourceService = buildSourceService(session)
        response = await sourceService.createUploadSource(
            enterpriseId=enterpriseId,
            actorId=identity.actorId,
            displayName=displayName,
            versionLabel=versionLabel,
            principalIds=parsePrincipalIds(principalIds),
            fileName=file.filename or "upload.bin",
            mimeType=file.content_type,
            content=rawContent,
            documentId=documentId,
            sourceAuthority=sourceAuthority,
            extractionQuality=extractionQuality,
            publishedAt=parseOptionalTimestamp(publishedAt),
            metadata=parseOptionalMetadata(metadata),
        )
        await persistControlPlaneAudit(
            session=session,
            settings=settings,
            enterpriseId=enterpriseId,
            actorId=identity.actorId,
            action="source.upload.create",
            scope={
                "enterpriseId": str(enterpriseId),
                "documentId": str(response.documentId),
                "documentVersionId": str(response.documentVersionId),
            },
            outcome="queued",
            eventPayload={
                "displayName": displayName.strip(),
                "fileName": file.filename or "upload.bin",
                "mimeType": file.content_type,
                "jobId": str(response.jobId),
            },
        )
        await session.commit()
        return response
    except CortexError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)
        ) from error
    except Exception as error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"source upload failed: {error}",
        ) from error


@router.post("/v1/sources/website", response_model=CreateWebsiteSourceResponse)
async def createWebsiteSource(
    httpRequest: Request,
    request: CreateWebsiteSourceRequest,
    session: DatabaseSession,
) -> CreateWebsiteSourceResponse:
    """Fetch one allowlisted page, persist its snapshot, and queue deterministic ingestion."""
    identity = await requireAdminIdentity(
        request=httpRequest,
        session=session,
        settings=settings,
        action="source.website.create",
        enterpriseId=request.enterpriseId,
    )
    try:
        sourceService = buildSourceService(session)
        response = await sourceService.createWebsiteSource(request, actorId=identity.actorId)
        await persistControlPlaneAudit(
            session=session,
            settings=settings,
            enterpriseId=request.enterpriseId,
            actorId=identity.actorId,
            action="source.website.create",
            scope={
                "enterpriseId": str(request.enterpriseId),
                "documentId": str(response.documentId),
                "documentVersionId": str(response.documentVersionId),
            },
            outcome="queued",
            eventPayload={
                "displayName": request.displayName.strip(),
                "jobId": str(response.jobId),
                "sourceUri": request.sourceUri,
            },
        )
        await session.commit()
        return response
    except CortexError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)
        ) from error
    except Exception as error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"website source failed: {error}",
        ) from error


@router.get("/v1/sources", response_model=list[SourceSummaryResponse])
async def listSources(
    request: Request,
    enterpriseId: UUID,
    session: DatabaseSession,
) -> list[SourceSummaryResponse]:
    """Return the developer source inventory with the latest version status for each source."""
    await requireBuilderIdentity(
        request=request,
        session=session,
        settings=settings,
        action="source.list",
        enterpriseId=enterpriseId,
    )
    sourceService = buildSourceService(session)
    return await sourceService.listSources(enterpriseId)


@router.get("/v1/sources/{documentId}", response_model=SourceDetailResponse)
async def getSourceDetail(
    request: Request,
    documentId: UUID,
    enterpriseId: UUID,
    session: DatabaseSession,
) -> SourceDetailResponse:
    """Return one source record plus its ordered version history."""
    await requireBuilderIdentity(
        request=request,
        session=session,
        settings=settings,
        action="source.detail",
        enterpriseId=enterpriseId,
    )
    sourceService = buildSourceService(session)
    try:
        return await sourceService.getSourceDetail(enterpriseId, documentId)
    except CortexError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error


@router.get("/v1/jobs", response_model=list[JobSummaryResponse])
async def listJobs(
    request: Request,
    enterpriseId: UUID,
    session: DatabaseSession,
) -> list[JobSummaryResponse]:
    """Return the newest durable jobs for the developer jobs panel."""
    await requireBuilderIdentity(
        request=request,
        session=session,
        settings=settings,
        action="job.list",
        enterpriseId=enterpriseId,
    )
    sourceService = buildSourceService(session)
    return await sourceService.listJobs(enterpriseId)


@router.get("/v1/jobs/{jobId}", response_model=JobStatusResponse)
async def getJobStatus(
    request: Request,
    jobId: UUID,
    session: DatabaseSession,
) -> JobStatusResponse:
    """Return one persisted durable job row for polling and failure inspection."""
    sourceService = buildSourceService(session)
    jobStatus = await sourceService.getJobStatus(jobId)
    if jobStatus is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="job not found")
    await requireBuilderIdentity(
        request=request,
        session=session,
        settings=settings,
        action="job.detail",
        enterpriseId=jobStatus.enterpriseId,
    )
    return jobStatus


@router.post("/v1/query", response_model=QueryResponse)
async def submitQuery(
    request: QueryRequest,
    session: DatabaseSession,
) -> QueryResponse:
    """Execute the fixed query route and return only validated claims."""
    try:
        queryService = QueryService(
            session=session,
            settings=settings,
            modelProvider=buildModelProvider(settings),
        )
        return await queryService.answerQuery(request)
    except CortexError as error:
        raise mapCortexErrorToHttp(error) from error
    except Exception as error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="query failed"
        ) from error


@router.post("/v1/chat/completions", response_model=ChatCompletionResponseSchema)
async def submitChatCompletion(
    httpRequest: Request,
    httpResponse: Response,
    request: ChatCompletionRequestSchema,
    session: DatabaseSession,
) -> ChatCompletionResponseSchema:
    """Expose one OpenAI-compatible query facade for replacement client chat surfaces."""
    if request.stream:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="streaming chat completions are not supported; use SSE trace events instead",
        )
    identity = await resolveIdentity(httpRequest, settings)
    latestUserMessage = next(
        (
            message.content.strip()
            for message in reversed(request.messages)
            if message.role == "user" and message.content.strip()
        ),
        "",
    )
    if not latestUserMessage:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="the last user message cannot be empty",
        )
    queryService = QueryService(
        session=session,
        settings=settings,
        modelProvider=buildModelProvider(settings),
    )
    try:
        queryResponse = await queryService.answerQuery(
            QueryRequest(
                query=latestUserMessage,
                accessScope={
                    "enterpriseId": identity.enterpriseId,
                    "actorId": identity.actorId,
                    "principalIds": list(identity.principalIds),
                },
                showCitations=request.cortex.showCitations,
            )
        )
    except CortexError as error:
        raise mapCortexErrorToHttp(error) from error
    except Exception as error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"chat completion failed: {error}",
        ) from error
    httpResponse.headers["X-Cortex-Contract-Version"] = "v1"
    httpResponse.headers["X-Cortex-Trace-Id"] = str(queryResponse.traceId)
    httpResponse.headers["X-Cortex-Evidence-Status"] = queryResponse.evidenceStatus
    httpResponse.headers["X-Cortex-Route"] = queryResponse.route
    httpResponse.headers["X-Cortex-Abstained"] = (
        "true" if queryResponse.evidenceStatus in {"insufficient", "conflict"} else "false"
    )
    return ChatCompletionResponseSchema(
        id=f"cortex-{queryResponse.traceId}",
        object="chat.completion",
        created=int(datetime.now(UTC).timestamp()),
        model=request.model,
        choices=[
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": queryResponse.answer,
                },
                "finish_reason": "stop",
            }
        ],
        x_cortex={
            "contractVersion": "v1",
            "traceId": queryResponse.traceId,
            "traceEventsPath": f"/v1/query/{queryResponse.traceId}/events",
            "route": queryResponse.route,
            "correctedQuery": queryResponse.correctedQuery,
            "evidenceStatus": queryResponse.evidenceStatus,
            "abstained": queryResponse.evidenceStatus in {"insufficient", "conflict"},
            "claims": queryResponse.claims,
            "citations": queryResponse.citations,
            "stages": queryResponse.stages,
        },
    )


@router.get("/v1/query/{traceId}/events")
async def streamQueryEvents(
    traceId: UUID,
    request: Request,
    session: DatabaseSession,
) -> StreamingResponse:
    """Stream persisted stage-level progress without exposing unvalidated answer tokens."""
    queryService = QueryService(
        session=session,
        settings=settings,
        modelProvider=buildModelProvider(settings),
    )
    traceSummary = await queryService.getTrace(traceId)
    if traceSummary is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="trace not found")
    await requireBuilderIdentity(
        request=request,
        session=session,
        settings=settings,
        action="trace.events.read",
        enterpriseId=traceSummary.enterpriseId,
    )

    async def generateEvents():
        try:
            for stageEvent in traceSummary.stageEvents:
                if await request.is_disconnected():
                    return
                yield (f"event: stage\ndata: {json.dumps(stageEvent.model_dump(mode='json'))}\n\n")
                await asyncio.sleep(0.12)
            if await request.is_disconnected():
                return
            yield f"event: complete\ndata: {json.dumps({'traceId': str(traceId)})}\n\n"
        except asyncio.CancelledError:
            return

    return StreamingResponse(generateEvents(), media_type="text/event-stream")


@router.get("/v1/traces/latest", response_model=TraceSummaryResponse | None)
async def getLatestTrace(
    request: Request,
    enterpriseId: UUID,
    session: DatabaseSession,
) -> TraceSummaryResponse | None:
    """Return the latest trace for the developer console trace timeline."""
    await requireBuilderIdentity(
        request=request,
        session=session,
        settings=settings,
        action="trace.latest.read",
        enterpriseId=enterpriseId,
    )
    queryService = QueryService(
        session=session,
        settings=settings,
        modelProvider=buildModelProvider(settings),
    )
    return await queryService.getLatestTrace(enterpriseId)


@router.get("/v1/traces/{traceId}", response_model=TraceSummaryResponse)
async def getTrace(
    traceId: UUID,
    request: Request,
    session: DatabaseSession,
) -> TraceSummaryResponse:
    """Return one persisted trace and its exact stage timeline."""
    queryService = QueryService(
        session=session,
        settings=settings,
        modelProvider=buildModelProvider(settings),
    )
    traceSummary = await queryService.getTrace(traceId)
    if traceSummary is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="trace not found")
    await requireBuilderIdentity(
        request=request,
        session=session,
        settings=settings,
        action="trace.detail.read",
        enterpriseId=traceSummary.enterpriseId,
    )
    return traceSummary


@router.post("/v1/dev/seed", response_model=SeedFixturesResponse)
async def seedDevelopmentFixtures(
    request: Request,
    session: DatabaseSession,
) -> SeedFixturesResponse:
    """Seed a deterministic fixture corpus for the live integration baseline."""
    await requireAdminIdentity(
        request=request,
        session=session,
        settings=settings,
        action="fixtures.seed",
        enterpriseId=settings.enterpriseId,
    )
    identity = await resolveIdentity(request, settings)
    try:
        response = await seedFixtures(
            session,
            settings,
            buildModelProvider(settings),
            includeSampleTraces=False,
        )
        await persistControlPlaneAudit(
            session=session,
            settings=settings,
            enterpriseId=settings.enterpriseId,
            actorId=identity.actorId,
            action="fixtures.seed",
            scope={"enterpriseId": str(settings.enterpriseId)},
            outcome="seeded",
            eventPayload={
                "seededDocuments": response.seededDocuments,
                "traceCount": response.traceCount,
            },
        )
        await session.commit()
        return response
    except Exception as error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"fixture seeding failed: {error}",
        ) from error


@router.get("/v1/pipelines/active", response_model=PipelineGraphResponse)
async def getActivePipeline(
    request: Request,
    enterpriseId: UUID,
    session: DatabaseSession,
) -> PipelineGraphResponse:
    """Return the active persisted pipeline graph rendered by the developer console."""
    identity = await requireBuilderIdentity(
        request=request,
        session=session,
        settings=settings,
        action="pipeline.active.read",
        enterpriseId=enterpriseId,
    )
    return await buildPipelineService(session).getOrCreateActivePipeline(identity)


@router.get("/v1/pipelines/versions", response_model=list[PipelineVersionSummaryResponse])
async def listPipelineVersions(
    request: Request,
    enterpriseId: UUID,
    session: DatabaseSession,
) -> list[PipelineVersionSummaryResponse]:
    """List immutable persisted pipeline versions for governance review and rollback."""
    await requireBuilderIdentity(
        request=request,
        session=session,
        settings=settings,
        action="pipeline.versions.list",
        enterpriseId=enterpriseId,
    )
    return await buildPipelineService(session).listPipelineVersions(enterpriseId)


@router.post("/v1/pipelines/validate", response_model=PipelineGraphResponse)
async def validatePipeline(
    request: Request,
    payload: ValidatePipelineRequest,
    session: DatabaseSession,
) -> PipelineGraphResponse:
    """Validate the next persisted pipeline draft and record the audited promotion event."""
    identity = await requireAdminIdentity(
        request=request,
        session=session,
        settings=settings,
        action="pipeline.validate",
        enterpriseId=payload.enterpriseId,
    )
    return await buildPipelineService(session).validateNextPipeline(identity)


@router.post("/v1/pipelines/activate", response_model=PipelineGraphResponse)
async def activatePipeline(
    request: Request,
    payload: ActivatePipelineRequest,
    session: DatabaseSession,
) -> PipelineGraphResponse:
    """Activate a validated pipeline version or roll back to a previously approved version."""
    identity = await requireAdminIdentity(
        request=request,
        session=session,
        settings=settings,
        action="pipeline.activate",
        enterpriseId=payload.enterpriseId,
    )
    return await buildPipelineService(session).activatePipeline(
        identity=identity,
        version=payload.version,
    )


def parseOptionalTimestamp(timestampValue: str | None) -> datetime | None:
    """Parse optional ISO timestamps supplied through the ingestion API."""
    if timestampValue is None:
        return None
    return datetime.fromisoformat(timestampValue.replace("Z", "+00:00")).astimezone(UTC)


def parsePrincipalIds(rawPrincipalIds: str) -> list[str]:
    """Parse principals supplied through multipart forms as JSON or comma-separated text."""
    normalizedValue = rawPrincipalIds.strip()
    if not normalizedValue:
        raise ValueError("principalIds cannot be empty")
    if normalizedValue.startswith("["):
        parsedValue = json.loads(normalizedValue)
        if not isinstance(parsedValue, list):
            raise ValueError("principalIds JSON must be a list")
        return [str(principalId) for principalId in parsedValue]
    return [
        principalId.strip()
        for principalId in normalizedValue.split(",")
        if principalId.strip()
    ]


def parseOptionalMetadata(rawMetadata: str | None) -> dict[str, object]:
    """Parse optional metadata supplied through multipart forms as a JSON object."""
    if rawMetadata is None or not rawMetadata.strip():
        return {}
    parsedMetadata = json.loads(rawMetadata)
    if not isinstance(parsedMetadata, dict):
        raise ValueError("metadata must be a JSON object")
    return {str(key): value for key, value in parsedMetadata.items()}

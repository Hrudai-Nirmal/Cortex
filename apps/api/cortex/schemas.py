"""Versioned API schemas for ingestion, querying, traces, and pipeline operations."""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AccessScopeSchema(BaseModel):
    """Carry authenticated retrieval principals supplied by the identity layer."""

    enterpriseId: UUID
    actorId: str = Field(min_length=1, max_length=255)
    principalIds: list[str] = Field(min_length=1, max_length=100)

    @field_validator("principalIds")
    @classmethod
    def validatePrincipals(cls, principalIds: list[str]) -> list[str]:
        """Normalize and deduplicate ACL principals without widening scope."""
        normalizedPrincipals = tuple(dict.fromkeys(principal.strip() for principal in principalIds))
        if any(not principal for principal in normalizedPrincipals):
            raise ValueError("principal IDs cannot be empty")
        return list(normalizedPrincipals)


class IngestTextRequest(BaseModel):
    """Accept text ingestion for the executable vertical slice."""

    enterpriseId: UUID
    documentId: UUID
    documentTitle: str = Field(min_length=1, max_length=255)
    sourceUri: str = Field(min_length=1, max_length=2048)
    versionLabel: str = Field(min_length=1, max_length=120)
    content: str = Field(min_length=1, max_length=2_000_000)
    principalIds: list[str] = Field(min_length=1)
    chunkSize: int = Field(default=900, ge=64, le=8000)
    chunkOverlap: int = Field(default=120, ge=0, le=2000)
    sourceAuthority: float = Field(default=0.85, ge=0, le=1)
    extractionQuality: float = Field(default=0.9, ge=0, le=1)
    publishedAt: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class IngestTextResponse(BaseModel):
    """Return deterministic identifiers proving the ingestion result."""

    documentVersionId: UUID
    documentVersionHash: str
    chunkCount: int
    chunkIds: list[str]
    status: str


class CitationSchema(BaseModel):
    """Map an answer claim to an exact versioned source span."""

    citationId: str
    documentTitle: str
    documentVersion: str
    chunkId: str
    structuralLocator: str
    exactSpan: str
    supportScore: float = Field(ge=0, le=1)


class ClaimSchema(BaseModel):
    """Represent one independently validated answer claim."""

    claimId: str
    text: str
    confidence: float = Field(ge=0, le=1)
    citationIds: list[str]
    supportStatus: Literal["supported", "conflict", "insufficient"]


class StageSchema(BaseModel):
    """Describe one auditable execution stage shown in both APIs and UI traces."""

    name: str
    status: Literal["pending", "running", "complete", "failed"]
    durationMs: int = Field(ge=0)
    detail: str


class QueryRequest(BaseModel):
    """Submit an evidence-bounded user query with a mandatory access scope."""

    query: str = Field(min_length=2, max_length=4000)
    accessScope: AccessScopeSchema
    showCitations: bool = True


class QueryResponse(BaseModel):
    """Return only validated claims plus trace and evidence state."""

    traceId: UUID
    route: Literal["rag", "compute", "retrieve-then-compute"]
    correctedQuery: str | None
    answer: str
    evidenceStatus: Literal["sufficient", "partial", "insufficient", "conflict"]
    claims: list[ClaimSchema]
    citations: list[CitationSchema]
    stages: list[StageSchema]


class QueryStageEventSchema(BaseModel):
    """Represent one persisted trace event replayed through SSE or developer UI."""

    traceId: UUID
    stage: str
    position: int = Field(ge=1)
    status: Literal["pending", "running", "complete", "failed"]
    detail: str
    durationMs: int = Field(ge=0)


class RetrievedEvidenceSchema(BaseModel):
    """Expose one persisted retrieved-evidence row for operator trace inspection."""

    chunkId: str
    documentTitle: str
    documentVersion: str
    structuralLocator: str
    supportScore: float = Field(ge=0, le=1)
    sourceScore: float = Field(ge=0, le=1)
    rerankScore: float = Field(ge=0, le=1)
    contentPreview: str


class TraceSummaryResponse(BaseModel):
    """Expose the latest persisted trace for the developer operations surface."""

    traceId: UUID
    enterpriseId: UUID
    actorId: str
    route: Literal["rag", "compute", "retrieve-then-compute"]
    rawQuery: str
    correctedQuery: str | None
    answer: str | None
    evidenceStatus: Literal["sufficient", "partial", "insufficient", "conflict"]
    createdAt: str
    claims: list[ClaimSchema]
    citations: list[CitationSchema]
    stages: list[StageSchema]
    stageEvents: list[QueryStageEventSchema]
    retrievedEvidence: list[RetrievedEvidenceSchema] = Field(default_factory=list)
    pipelineVersion: int | None
    outcome: str


class RuntimeComponentSchema(BaseModel):
    """Describe the readiness state of one required runtime dependency."""

    name: str
    status: Literal["ready", "degraded", "unavailable"]
    severity: Literal["info", "warning", "error"]
    detail: str
    remediation: str | None = None


class RuntimeHealthResponse(BaseModel):
    """Return component health for developer tooling and deployment probes."""

    status: Literal["ready", "degraded"]
    environment: str
    components: list[RuntimeComponentSchema]


class ChatMessageSchema(BaseModel):
    """Carry one OpenAI-compatible chat message used by replacement query shells."""

    role: Literal["system", "user", "assistant"]
    content: str = Field(min_length=1, max_length=8000)


class ExternalQueryOptionsSchema(BaseModel):
    """Expose Cortex-specific query controls without leaving the OpenAI chat envelope."""

    showCitations: bool = True


class ChatCompletionRequestSchema(BaseModel):
    """Accept the minimal OpenAI-compatible request shape for client-owned chat shells."""

    model: str = Field(default="cortex-bounded-rag", min_length=1, max_length=255)
    messages: list[ChatMessageSchema] = Field(min_length=1, max_length=100)
    stream: bool = False
    cortex: ExternalQueryOptionsSchema = Field(default_factory=ExternalQueryOptionsSchema)

    @field_validator("messages")
    @classmethod
    def validateUserMessagePresence(
        cls, messages: list[ChatMessageSchema]
    ) -> list[ChatMessageSchema]:
        """Require at least one user message so deterministic routing has a clear query."""
        if not any(message.role == "user" for message in messages):
            raise ValueError("messages must include at least one user message")
        return messages


class ChatCompletionChoiceMessageSchema(BaseModel):
    """Return the assistant message in the shape expected by OpenAI-style clients."""

    role: Literal["assistant"]
    content: str


class ChatCompletionChoiceSchema(BaseModel):
    """Return one non-streaming assistant choice for the bounded Cortex answer."""

    model_config = ConfigDict(populate_by_name=True)

    index: int
    message: ChatCompletionChoiceMessageSchema
    finishReason: Literal["stop"] = Field(
        default="stop",
        alias="finish_reason",
        serialization_alias="finish_reason",
    )


class ExternalQueryMetadataSchema(BaseModel):
    """Expose evidence metadata replacement query shells need beside assistant text."""

    contractVersion: Literal["v1"]
    traceId: UUID
    traceEventsPath: str
    route: Literal["rag", "compute", "retrieve-then-compute"]
    correctedQuery: str | None
    evidenceStatus: Literal["sufficient", "partial", "insufficient", "conflict"]
    abstained: bool
    claims: list[ClaimSchema]
    citations: list[CitationSchema]
    stages: list[StageSchema]


class ExternalQueryRequestOptionsSchema(BaseModel):
    """Describe the stable request-shape rules replacement employee UIs must honor."""

    userMessageSelectionPolicy: Literal["last-non-empty-user-message"]
    streamRequiredValue: Literal[False]
    supportsCitationToggle: bool


class ExternalQueryErrorStatusSchema(BaseModel):
    """Describe one stable error class exported by the replacement-query facade."""

    statusCode: Literal[422, 403, 503, 500]
    code: Literal["invalid_request", "forbidden_scope", "provider_unavailable", "internal_error"]
    retryable: bool
    meaning: str


class ExternalQueryContractDescriptorSchema(BaseModel):
    """Describe the stable third-party query integration contract exported by Cortex."""

    contractVersion: Literal["v1"]
    endpointPath: str
    method: Literal["POST"]
    authentication: Literal["bearer-token"]
    supportsStreaming: bool
    requestOptions: ExternalQueryRequestOptionsSchema
    traceEventsPathTemplate: str
    operatorConsolePath: str
    responseHeaders: list[str] = Field(min_length=1)
    extensionFields: list[str] = Field(min_length=1)
    employeeSafeExtensionFields: list[str] = Field(min_length=1)
    operatorOnlyExtensionFields: list[str] = Field(min_length=1)
    errorStatuses: list[ExternalQueryErrorStatusSchema] = Field(min_length=1)
    evidenceStatuses: list[Literal["sufficient", "partial", "insufficient", "conflict"]] = (
        Field(min_length=1)
    )
    routes: list[Literal["rag", "compute", "retrieve-then-compute"]] = Field(min_length=1)
    abstentionEvidenceStatuses: list[Literal["insufficient", "conflict"]] = Field(
        min_length=1
    )
    notes: list[str] = Field(min_length=1)


class ChatCompletionResponseSchema(BaseModel):
    """Return an OpenAI-style chat completion plus Cortex evidence extension fields."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    object: Literal["chat.completion"]
    created: int = Field(ge=0)
    model: str
    choices: list[ChatCompletionChoiceSchema]
    xCortex: ExternalQueryMetadataSchema = Field(
        alias="x_cortex",
        serialization_alias="x_cortex",
    )


class SeedFixturesResponse(BaseModel):
    """Summarize the deterministic seed operation for local integration testing."""

    seededDocuments: int
    enterprises: list[UUID]
    traceCount: int


class QueuedJobResponse(BaseModel):
    """Return the durable job identifier for worker-executed operations."""

    jobId: UUID
    status: str


class CreateUploadSourceResponse(BaseModel):
    """Describe one queued file onboarding request and its deterministic source identifiers."""

    jobId: UUID
    documentId: UUID
    documentVersionId: UUID
    status: str


class CreateWebsiteSourceRequest(BaseModel):
    """Accept one allowlisted single-page website source for durable ingestion."""

    enterpriseId: UUID
    displayName: str = Field(min_length=1, max_length=255)
    sourceUri: str = Field(min_length=1, max_length=2048)
    versionLabel: str = Field(min_length=1, max_length=120)
    principalIds: list[str] = Field(min_length=1)
    documentId: UUID | None = None
    sourceAuthority: float = Field(default=0.85, ge=0, le=1)
    extractionQuality: float = Field(default=0.9, ge=0, le=1)
    publishedAt: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("principalIds")
    @classmethod
    def validateWebsitePrincipals(cls, principalIds: list[str]) -> list[str]:
        """Normalize ACL principals for website onboarding the same way query scope does."""
        return AccessScopeSchema.validatePrincipals(principalIds)


class CreateWebsiteSourceResponse(BaseModel):
    """Describe one queued website onboarding request and its deterministic source identifiers."""

    jobId: UUID
    documentId: UUID
    documentVersionId: UUID
    status: str


class SourceSummaryResponse(BaseModel):
    """Summarize one source record for the developer operations list."""

    documentId: UUID
    displayName: str
    sourceType: str
    sourceUri: str
    createdBy: str
    updatedAt: str
    latestVersionLabel: str | None
    latestIngestionStatus: str | None
    latestQuarantineStatus: str | None
    latestMalwareStatus: str | None
    latestPublishedAt: str | None
    latestActivatedAt: str | None
    principalIds: list[str]


class SourceVersionResponse(BaseModel):
    """Describe one document version and its ingestion diagnostics."""

    documentVersionId: UUID
    versionLabel: str
    status: str
    ingestionStatus: str
    quarantineStatus: str
    malwareStatus: str
    mimeType: str | None
    parserName: str
    parserVersion: str
    objectKey: str | None
    rawSha256: str
    canonicalContentSha256: str
    sourceAuthority: float = Field(ge=0, le=1)
    publishedAt: str | None
    createdAt: str
    activatedAt: str | None
    failureCode: str | None
    failureDetail: str | None
    extractionDiagnostics: dict[str, Any]
    acceleratorReports: list[dict[str, Any]]
    principalIds: list[str]


class SourceDetailResponse(BaseModel):
    """Expose one source record plus its ordered version history."""

    documentId: UUID
    displayName: str
    sourceType: str
    sourceUri: str
    createdBy: str
    updatedAt: str
    versions: list[SourceVersionResponse]


class JobStatusResponse(BaseModel):
    """Return persisted durable job status for developer operations and polling."""

    jobId: UUID
    enterpriseId: UUID
    jobType: str
    status: str
    attempts: int = Field(ge=0)
    availableAt: str
    lockedAt: str | None
    updatedAt: str
    lastError: str | None
    documentId: UUID | None
    documentVersionId: UUID | None
    sourceDisplayName: str | None


class JobSummaryResponse(BaseModel):
    """Summarize one durable job row for the developer jobs panel."""

    jobId: UUID
    jobType: str
    status: str
    attempts: int = Field(ge=0)
    updatedAt: str
    lastError: str | None
    documentId: UUID | None
    sourceDisplayName: str | None


class PipelineNodeSchema(BaseModel):
    """Expose graph data required by the developer console."""

    id: str
    label: str
    category: str
    status: str
    version: str
    config: dict[str, Any]


class PipelineGraphResponse(BaseModel):
    """Expose an immutable pipeline version and its promotion status."""

    name: str
    version: int
    status: str
    rerankTopK: int
    nodes: list[PipelineNodeSchema]
    edges: list[dict[str, str]]


class PipelineVersionSummaryResponse(BaseModel):
    """Summarize one immutable pipeline version for developer governance views."""

    pipelineVersionId: UUID
    enterpriseId: UUID
    version: int
    status: str
    createdBy: str
    createdAt: str
    activatedAt: str | None
    rerankTopK: int
    definitionHash: str


class ValidatePipelineRequest(BaseModel):
    """Request validation of the next persisted pipeline draft for one enterprise."""

    enterpriseId: UUID


class ActivatePipelineRequest(BaseModel):
    """Request activation of a validated pipeline version or rollback to an earlier one."""

    enterpriseId: UUID
    version: int | None = Field(default=None, ge=1)


class SessionResponse(BaseModel):
    """Expose the authenticated identity that the UI should render and honor."""

    enterpriseId: UUID
    actorId: str
    subject: str
    email: str
    displayName: str
    groups: list[str]
    roles: list[str]
    principalIds: list[str]
    isAdmin: bool
    isBuilder: bool

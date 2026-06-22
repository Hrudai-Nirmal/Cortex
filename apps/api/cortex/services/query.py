"""Persisted deterministic query orchestration for scoped retrieval and validated answers."""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from difflib import get_close_matches
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from cortex.config import Settings
from cortex.domain.compute import executeComputation
from cortex.errors import InputValidationError, ProviderOperationError
from cortex.schemas import (
    CitationSchema,
    ClaimSchema,
    QueryRequest,
    QueryResponse,
    QueryStageEventSchema,
    StageSchema,
    TraceSummaryResponse,
)
from cortex.services.audit import calculateAuditEventHash, calculateTraceIdentifierHash
from cortex.services.model_provider import OllamaModelProvider
from cortex.services.retrieval import (
    TOKEN_PATTERN,
    AccessScope,
    PostgresRetrievalService,
    RetrievedChunk,
)

NUMBER_PATTERN = re.compile(r"-?\d+(?:\.\d+)?")
DATE_DIFFERENCE_PATTERN = re.compile(
    r"days between (?P<start>\d{4}-\d{2}-\d{2}) and (?P<end>\d{4}-\d{2}-\d{2})",
    re.IGNORECASE,
)
SUM_PATTERN = re.compile(r"\b(sum|total)\b", re.IGNORECASE)
MEAN_PATTERN = re.compile(r"\b(mean|average)\b", re.IGNORECASE)
RETRIEVE_THEN_COMPUTE_HINTS = ("worksheet", "spreadsheet", "table", "values")
LEXICAL_NOISE_WORDS = {
    "a",
    "an",
    "are",
    "for",
    "how",
    "our",
    "rules",
    "the",
    "what",
}
SPELLING_LEXICON = (
    "retention",
    "authority",
    "freshness",
    "access",
    "authorized",
    "citation",
    "citations",
    "pipeline",
    "promotion",
    "compute",
    "sum",
    "average",
    "difference",
    "enterprise",
)


@dataclass(frozen=True, slots=True)
class QueryRouteDecision:
    """Describe the deterministic route chosen before retrieval or generation."""

    route: str
    functionName: str | None
    inputs: dict[str, Any]
    correctedQuery: str | None


@dataclass(frozen=True, slots=True)
class PersistedTraceRecord:
    """Carry a persisted trace payload for the developer operations surface."""

    traceId: UUID
    enterpriseId: UUID
    actorId: str
    route: str
    rawQuery: str
    correctedQuery: str | None
    answer: str | None
    evidenceStatus: str
    createdAt: str
    citations: list[CitationSchema]
    stages: list[StageSchema]
    stageEvents: list[QueryStageEventSchema]
    pipelineVersion: int | None
    outcome: str


class QueryService:
    """Execute the persisted evidence-first route without autonomous tool selection."""

    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        modelProvider: OllamaModelProvider,
    ) -> None:
        if session is None:
            raise ValueError("session is required")
        if settings is None:
            raise ValueError("settings are required")
        if modelProvider is None:
            raise ValueError("modelProvider is required")
        self.session = session
        self.settings = settings
        self.modelProvider = modelProvider
        self.retrievalService = PostgresRetrievalService(
            session=session,
            candidateLimit=settings.retrievalCandidateLimit,
            rerankTopK=settings.rerankTopK,
            sourceConfidenceThreshold=settings.sourceConfidenceThreshold,
        )

    async def answerQuery(self, request: QueryRequest) -> QueryResponse:
        """Retrieve authorized evidence and return only supported extractive claims."""
        accessScope = AccessScope(
            enterpriseId=request.accessScope.enterpriseId,
            actorId=request.accessScope.actorId,
            principalIds=tuple(request.accessScope.principalIds),
        )
        accessScope.validate()
        traceId = uuid4()
        traceCreatedAt = datetime.now(UTC)
        stageEvents: list[QueryStageEventSchema] = []
        stageStartTime = time.perf_counter()
        routeDecision = self._decideRoute(request.query)
        stageEvents.append(
            self._buildStageEvent(
                traceId=traceId,
                stageName="Classify",
                position=1,
                detail=f"{routeDecision.route} route",
                stageStartTime=stageStartTime,
            )
        )

        if routeDecision.route == "compute":
            response = self._buildComputeResponse(
                traceId=traceId,
                routeDecision=routeDecision,
                stageEvents=stageEvents,
            )
            await self._persistTraceAndAudit(
                request=request,
                response=response,
                routeDecision=routeDecision,
                stageEvents=stageEvents,
                retrievedChunks=[],
                traceCreatedAt=traceCreatedAt,
            )
            return response

        retrievalStartTime = time.perf_counter()
        queryEmbedding = (await self.modelProvider.embedTexts([request.query]))[0]
        retrievalQuery = routeDecision.correctedQuery or request.query
        retrievedChunks = await self.retrievalService.retrieve(
            queryText=retrievalQuery,
            queryEmbedding=queryEmbedding,
            accessScope=accessScope,
        )
        fallbackQuery = buildFocusedRetrievalQuery(retrievalQuery)
        if not retrievedChunks and fallbackQuery is not None:
            retrievedChunks = await self.retrievalService.retrieve(
                queryText=fallbackQuery,
                queryEmbedding=queryEmbedding,
                accessScope=accessScope,
            )
        stageEvents.append(
            self._buildStageEvent(
                traceId=traceId,
                stageName="Scoped hybrid retrieval",
                position=2,
                detail=f"{len(retrievedChunks)} authorized candidates after threshold",
                stageStartTime=retrievalStartTime,
            )
        )
        if routeDecision.route == "retrieve-then-compute":
            response = self._buildRetrieveThenComputeResponse(
                traceId=traceId,
                routeDecision=routeDecision,
                retrievedChunks=retrievedChunks,
                stageEvents=stageEvents,
            )
            await self._persistTraceAndAudit(
                request=request,
                response=response,
                routeDecision=routeDecision,
                stageEvents=stageEvents,
                retrievedChunks=retrievedChunks,
                traceCreatedAt=traceCreatedAt,
            )
            return response

        rerankStartTime = time.perf_counter()
        stageEvents.append(
            self._buildStageEvent(
                traceId=traceId,
                stageName="RRF + rerank",
                position=3,
                detail=f"Top {min(len(retrievedChunks), self.settings.rerankTopK)} candidates",
                stageStartTime=rerankStartTime,
            )
        )
        validationStartTime = time.perf_counter()
        claims, citations, evidenceStatus = await self._generateValidatedClaims(retrievedChunks)
        finalDetail = (
            f"{len(claims)} supported claims"
            if claims
            else "No independently supported claims passed validation"
        )
        stageEvents.append(
            self._buildStageEvent(
                traceId=traceId,
                stageName="Claim validation",
                position=4,
                detail=finalDetail,
                stageStartTime=validationStartTime,
            )
        )
        response = self._buildRagResponse(
            traceId=traceId,
            routeDecision=routeDecision,
            claims=claims,
            citations=citations,
            evidenceStatus=evidenceStatus,
            stageEvents=stageEvents,
        )
        await self._persistTraceAndAudit(
            request=request,
            response=response,
            routeDecision=routeDecision,
            stageEvents=stageEvents,
            retrievedChunks=retrievedChunks,
            traceCreatedAt=traceCreatedAt,
        )
        return response

    async def getLatestTrace(self, enterpriseId: UUID) -> TraceSummaryResponse | None:
        """Return the most recent persisted trace for the developer operations view."""
        result = await self.session.execute(
            text(
                """
                SELECT
                    tm.id, tm.enterprise_id, tm.actor_id, tm.raw_query, tm.raw_response,
                    tm.payload,
                       tm.created_at, al.pipeline_version, al.outcome
                FROM trace_memory AS tm
                LEFT JOIN audit_log AS al ON al.trace_memory_id = tm.id
                WHERE tm.enterprise_id = :enterprise_id
                ORDER BY tm.created_at DESC
                LIMIT 1
                """
            ),
            {"enterprise_id": enterpriseId},
        )
        row = result.mappings().first()
        if row is None:
            return None
        return self._rowToTraceSummary(row)

    async def getTrace(self, traceId: UUID) -> TraceSummaryResponse | None:
        """Load one persisted trace by its stable identifier."""
        result = await self.session.execute(
            text(
                """
                SELECT
                    tm.id, tm.enterprise_id, tm.actor_id, tm.raw_query, tm.raw_response,
                    tm.payload,
                       tm.created_at, al.pipeline_version, al.outcome
                FROM trace_memory AS tm
                LEFT JOIN audit_log AS al ON al.trace_memory_id = tm.id
                WHERE tm.id = :trace_id
                LIMIT 1
                """
            ),
            {"trace_id": traceId},
        )
        row = result.mappings().first()
        if row is None:
            return None
        return self._rowToTraceSummary(row)

    def _decideRoute(self, queryText: str) -> QueryRouteDecision:
        correctedQuery = buildCorrectedQuery(queryText)
        normalizedQuery = (correctedQuery or queryText).strip()
        dateMatch = DATE_DIFFERENCE_PATTERN.search(normalizedQuery)
        if dateMatch:
            return QueryRouteDecision(
                route="compute",
                functionName="dateDifference",
                inputs={
                    "startDate": dateMatch.group("start"),
                    "endDate": dateMatch.group("end"),
                },
                correctedQuery=correctedQuery,
            )
        inlineNumbers = [float(value) for value in NUMBER_PATTERN.findall(normalizedQuery)]
        if inlineNumbers and SUM_PATTERN.search(normalizedQuery):
            return QueryRouteDecision(
                route="compute",
                functionName="sum",
                inputs={"values": inlineNumbers},
                correctedQuery=correctedQuery,
            )
        if inlineNumbers and MEAN_PATTERN.search(normalizedQuery):
            return QueryRouteDecision(
                route="compute",
                functionName="mean",
                inputs={"values": inlineNumbers},
                correctedQuery=correctedQuery,
            )
        if any(hint in normalizedQuery.lower() for hint in RETRIEVE_THEN_COMPUTE_HINTS) and (
            SUM_PATTERN.search(normalizedQuery) or MEAN_PATTERN.search(normalizedQuery)
        ):
            functionName = "mean" if MEAN_PATTERN.search(normalizedQuery) else "sum"
            return QueryRouteDecision(
                route="retrieve-then-compute",
                functionName=functionName,
                inputs={},
                correctedQuery=correctedQuery,
            )
        return QueryRouteDecision(
            route="rag",
            functionName=None,
            inputs={},
            correctedQuery=correctedQuery,
        )

    def _buildComputeResponse(
        self,
        traceId: UUID,
        routeDecision: QueryRouteDecision,
        stageEvents: list[QueryStageEventSchema],
    ) -> QueryResponse:
        if routeDecision.functionName is None:
            raise InputValidationError("compute route requires a function name")
        computeResult = executeComputation(routeDecision.functionName, routeDecision.inputs)
        answer = (
            f"{computeResult.functionName} = {computeResult.value:g}"
            if isinstance(computeResult.value, float)
            else f"{computeResult.functionName} = {computeResult.value}"
        )
        stageEvents.append(
            QueryStageEventSchema(
                traceId=traceId,
                stage="Claim validation",
                position=2,
                status="complete",
                detail="Typed deterministic computation completed",
                durationMs=1,
            )
        )
        return QueryResponse(
            traceId=traceId,
            route="compute",
            correctedQuery=routeDecision.correctedQuery,
            answer=answer,
            evidenceStatus="sufficient",
            claims=[
                ClaimSchema(
                    claimId="compute-1",
                    text=answer,
                    confidence=1.0,
                    citationIds=[],
                    supportStatus="supported",
                )
            ],
            citations=[],
            stages=self._convertStageEvents(stageEvents),
        )

    def _buildRetrieveThenComputeResponse(
        self,
        traceId: UUID,
        routeDecision: QueryRouteDecision,
        retrievedChunks: list[RetrievedChunk],
        stageEvents: list[QueryStageEventSchema],
    ) -> QueryResponse:
        if routeDecision.functionName is None:
            raise InputValidationError("retrieve-then-compute route requires a function name")
        values = extractNumericValues(retrievedChunks)
        if not values:
            stageEvents.append(
                QueryStageEventSchema(
                    traceId=traceId,
                    stage="Claim validation",
                    position=3,
                    status="complete",
                    detail="No numeric evidence could be computed safely",
                    durationMs=1,
                )
            )
            return QueryResponse(
                traceId=traceId,
                route="retrieve-then-compute",
                correctedQuery=routeDecision.correctedQuery,
                answer=(
                    "I found authorized evidence but not enough structured values "
                    "to compute a result."
                ),
                evidenceStatus="insufficient",
                claims=[],
                citations=[],
                stages=self._convertStageEvents(stageEvents),
            )
        computeResult = executeComputation(routeDecision.functionName, {"values": values})
        citations = buildCitations(retrievedChunks[: min(2, len(retrievedChunks))])
        answer = f"{computeResult.functionName} = {computeResult.value:g}"
        stageEvents.append(
            QueryStageEventSchema(
                traceId=traceId,
                stage="Claim validation",
                position=3,
                status="complete",
                detail=f"Computed from {len(values)} retrieved values",
                durationMs=1,
            )
        )
        return QueryResponse(
            traceId=traceId,
            route="retrieve-then-compute",
            correctedQuery=routeDecision.correctedQuery,
            answer=answer,
            evidenceStatus="sufficient",
            claims=[
                ClaimSchema(
                    claimId="compute-1",
                    text=answer,
                    confidence=0.96,
                    citationIds=[citation.citationId for citation in citations],
                    supportStatus="supported",
                )
            ],
            citations=citations,
            stages=self._convertStageEvents(stageEvents),
        )

    async def _generateValidatedClaims(
        self,
        retrievedChunks: list[RetrievedChunk],
    ) -> tuple[list[ClaimSchema], list[CitationSchema], str]:
        if not retrievedChunks:
            return [], [], "insufficient"
        responseSchema = {
            "type": "object",
            "additionalProperties": False,
            "required": ["claims"],
            "properties": {
                "claims": {
                    "type": "array",
                    "maxItems": 2,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["chunkId", "text"],
                        "properties": {
                            "chunkId": {"type": "string"},
                            "text": {"type": "string", "minLength": 1, "maxLength": 240},
                        },
                    },
                }
            },
        }
        evidenceBlock = "\n\n".join(
            [
                "\n".join(
                    [
                        f"chunk_id: {chunk.chunkId}",
                        f"title: {chunk.documentTitle}",
                        f"version: {chunk.documentVersion}",
                        f"support_score: {chunk.supportScore:.3f}",
                        f"content: {chunk.content}",
                    ]
                )
                for chunk in retrievedChunks[:4]
            ]
        )
        systemPrompt = (
            "Return only short exact atomic claims copied verbatim from the provided evidence. "
            "Do not paraphrase, infer, or use outside knowledge. Return an empty claims array "
            "when the evidence is weak or conflicting."
        )
        userPrompt = (
            f"Evidence:\n{evidenceBlock}\n\n"
            "Return up to 2 exact supported claims. Keep each claim under 240 characters."
        )
        generatedClaims = await self.modelProvider.generateStructured(
            systemPrompt=systemPrompt,
            userPrompt=userPrompt,
            responseSchema=responseSchema,
        )
        claimsPayload = generatedClaims.get("claims")
        if not isinstance(claimsPayload, list):
            raise ProviderOperationError("generator returned an invalid claims payload")
        claimRows: list[ClaimSchema] = []
        citationRows: list[CitationSchema] = []
        citationIndex = 1
        for claimIndex, claimValue in enumerate(claimsPayload, start=1):
            if not isinstance(claimValue, dict):
                continue
            chunkId = claimValue.get("chunkId")
            claimText = claimValue.get("text")
            if not isinstance(chunkId, str) or not isinstance(claimText, str):
                continue
            supportingChunk = next(
                (chunk for chunk in retrievedChunks if chunk.chunkId == chunkId),
                None,
            )
            if supportingChunk is None:
                continue
            normalizedClaim = claimText.strip()
            if not normalizedClaim or normalizedClaim not in supportingChunk.content:
                continue
            citationId = f"C{citationIndex}"
            citationIndex += 1
            citationRows.append(
                CitationSchema(
                    citationId=citationId,
                    documentTitle=supportingChunk.documentTitle,
                    documentVersion=supportingChunk.documentVersion,
                    chunkId=supportingChunk.chunkId,
                    structuralLocator=supportingChunk.structuralLocator,
                    exactSpan=normalizedClaim,
                    supportScore=round(supportingChunk.supportScore, 4),
                )
            )
            claimRows.append(
                ClaimSchema(
                    claimId=f"claim-{claimIndex}",
                    text=normalizedClaim,
                    confidence=round(supportingChunk.supportScore, 4),
                    citationIds=[citationId],
                    supportStatus="supported",
                )
            )
        if claimRows:
            return claimRows, citationRows, "sufficient"
        topChunk = retrievedChunks[0]
        if topChunk.supportScore >= max(self.settings.sourceConfidenceThreshold, 0.7):
            fallbackCitation = CitationSchema(
                citationId="C1",
                documentTitle=topChunk.documentTitle,
                documentVersion=topChunk.documentVersion,
                chunkId=topChunk.chunkId,
                structuralLocator=topChunk.structuralLocator,
                exactSpan=topChunk.content,
                supportScore=round(topChunk.supportScore, 4),
            )
            fallbackClaim = ClaimSchema(
                claimId="claim-1",
                text=topChunk.content,
                confidence=round(topChunk.supportScore, 4),
                citationIds=[fallbackCitation.citationId],
                supportStatus="supported",
            )
            return [fallbackClaim], [fallbackCitation], "sufficient"
        if hasConflictingEvidence(retrievedChunks):
            return [], buildCitations(retrievedChunks[:2]), "conflict"
        return [], [], "insufficient"

    def _buildRagResponse(
        self,
        traceId: UUID,
        routeDecision: QueryRouteDecision,
        claims: list[ClaimSchema],
        citations: list[CitationSchema],
        evidenceStatus: str,
        stageEvents: list[QueryStageEventSchema],
    ) -> QueryResponse:
        if claims:
            answer = " ".join(claim.text for claim in claims)
        elif evidenceStatus == "conflict":
            answer = "I found conflicting authorized evidence and cannot answer confidently."
        else:
            answer = "I could not find enough authorized evidence to answer that question."
        return QueryResponse(
            traceId=traceId,
            route="rag",
            correctedQuery=routeDecision.correctedQuery,
            answer=answer,
            evidenceStatus=evidenceStatus,
            claims=claims,
            citations=citations,
            stages=self._convertStageEvents(stageEvents),
        )

    async def _persistTraceAndAudit(
        self,
        request: QueryRequest,
        response: QueryResponse,
        routeDecision: QueryRouteDecision,
        stageEvents: list[QueryStageEventSchema],
        retrievedChunks: list[RetrievedChunk],
        traceCreatedAt: datetime,
    ) -> None:
        tracePayload = {
            "route": response.route,
            "correctedQuery": routeDecision.correctedQuery,
            "evidenceStatus": response.evidenceStatus,
            "stages": [stage.model_dump() for stage in response.stages],
            "stageEvents": [stageEvent.model_dump(mode="json") for stageEvent in stageEvents],
            "citations": [citation.model_dump() for citation in response.citations],
            "claims": [claim.model_dump() for claim in response.claims],
            "retrievedText": [chunk.content for chunk in retrievedChunks],
            "retrievedChunks": [
                {
                    "chunkId": chunk.chunkId,
                    "title": chunk.documentTitle,
                    "version": chunk.documentVersion,
                    "supportScore": chunk.supportScore,
                    "sourceScore": chunk.sourceScore,
                    "rerankScore": chunk.rerankScore,
                }
                for chunk in retrievedChunks
            ],
            "modelInputs": {
                "rawQuery": request.query,
                "correctedQuery": routeDecision.correctedQuery,
            },
        }
        rawContentExpiresAt = traceCreatedAt + timedelta(
            days=self.settings.queryContentRetentionDays
        )
        traceExpiresAt = traceCreatedAt + timedelta(days=self.settings.traceRetentionDays)
        auditExpiresAt = traceCreatedAt + timedelta(days=self.settings.auditRetentionDays)
        traceIdentifierHash = calculateTraceIdentifierHash(response.traceId)
        auditEventId = uuid4()
        auditScope = {
            "enterpriseId": str(request.accessScope.enterpriseId),
            "principalCount": len(request.accessScope.principalIds),
            "route": response.route,
        }
        auditEventHash = calculateAuditEventHash(
            eventId=auditEventId,
            enterpriseId=request.accessScope.enterpriseId,
            traceIdentifierHash=traceIdentifierHash,
            actorId=request.accessScope.actorId,
            action="query.answer",
            scope=auditScope,
            outcome=response.evidenceStatus,
            createdAt=traceCreatedAt,
        )
        try:
            await self.session.execute(
                text(
                    """
                    INSERT INTO trace_memory (
                        id, enterprise_id, actor_id, raw_query, raw_response, payload,
                        created_at, raw_content_expires_at, expires_at
                    ) VALUES (
                        :trace_id, :enterprise_id, :actor_id, :raw_query, :raw_response,
                        CAST(:payload AS jsonb), :created_at, :raw_content_expires_at, :expires_at
                    )
                    """
                ),
                {
                    "trace_id": response.traceId,
                    "enterprise_id": request.accessScope.enterpriseId,
                    "actor_id": request.accessScope.actorId,
                    "raw_query": request.query,
                    "raw_response": response.answer,
                    "payload": json.dumps(tracePayload, sort_keys=True, separators=(",", ":")),
                    "created_at": traceCreatedAt,
                    "raw_content_expires_at": rawContentExpiresAt,
                    "expires_at": traceExpiresAt,
                },
            )
            await self.session.execute(
                text(
                    """
                    INSERT INTO audit_log (
                        id, enterprise_id, trace_memory_id, trace_identifier_hash,
                        actor_id, action, scope, pipeline_version, model_versions,
                        outcome, event_payload, event_hash, created_at, expires_at
                    ) VALUES (
                        :audit_id, :enterprise_id, :trace_memory_id, :trace_identifier_hash,
                        :actor_id, :action, CAST(:scope AS jsonb), :pipeline_version,
                        CAST(:model_versions AS jsonb), :outcome, CAST(:event_payload AS jsonb),
                        :event_hash, :created_at, :expires_at
                    )
                    """
                ),
                {
                    "audit_id": auditEventId,
                    "enterprise_id": request.accessScope.enterpriseId,
                    "trace_memory_id": response.traceId,
                    "trace_identifier_hash": traceIdentifierHash,
                    "actor_id": request.accessScope.actorId,
                    "action": "query.answer",
                    "scope": json.dumps(auditScope, sort_keys=True, separators=(",", ":")),
                    "pipeline_version": self.settings.pipelineVersion,
                    "model_versions": json.dumps(
                        {
                            "generator": self.settings.generatorModel,
                            "embedding": self.settings.embeddingModel,
                        },
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    "outcome": response.evidenceStatus,
                    "event_payload": json.dumps(
                        {
                            "action": "query.answer",
                            "traceIdentifierHash": traceIdentifierHash.hex(),
                            "route": response.route,
                        },
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    "event_hash": auditEventHash,
                    "created_at": traceCreatedAt,
                    "expires_at": auditExpiresAt,
                },
            )
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise

    def _buildStageEvent(
        self,
        traceId: UUID,
        stageName: str,
        position: int,
        detail: str,
        stageStartTime: float,
    ) -> QueryStageEventSchema:
        return QueryStageEventSchema(
            traceId=traceId,
            stage=stageName,
            position=position,
            status="complete",
            detail=detail,
            durationMs=max(1, int((time.perf_counter() - stageStartTime) * 1000)),
        )

    def _convertStageEvents(
        self,
        stageEvents: list[QueryStageEventSchema],
    ) -> list[StageSchema]:
        return [
            StageSchema(
                name=stageEvent.stage,
                status=stageEvent.status,
                durationMs=stageEvent.durationMs,
                detail=stageEvent.detail,
            )
            for stageEvent in stageEvents
        ]

    def _rowToTraceSummary(self, row: Any) -> TraceSummaryResponse:
        payload = row["payload"] if isinstance(row["payload"], dict) else {}
        claims = [ClaimSchema.model_validate(claim) for claim in payload.get("claims", [])]
        citations = [
            CitationSchema.model_validate(citation) for citation in payload.get("citations", [])
        ]
        stages = [StageSchema.model_validate(stage) for stage in payload.get("stages", [])]
        stageEvents = [
            QueryStageEventSchema.model_validate(stageEvent)
            for stageEvent in payload.get("stageEvents", [])
        ]
        return TraceSummaryResponse(
            traceId=row["id"],
            enterpriseId=row["enterprise_id"],
            actorId=row["actor_id"],
            route=payload.get("route", "rag"),
            rawQuery=row["raw_query"],
            correctedQuery=payload.get("correctedQuery"),
            answer=row["raw_response"],
            evidenceStatus=payload.get("evidenceStatus", "insufficient"),
            createdAt=row["created_at"].astimezone(UTC).isoformat(),
            claims=claims,
            citations=citations,
            stages=stages,
            stageEvents=stageEvents,
            pipelineVersion=row["pipeline_version"],
            outcome=row["outcome"] or payload.get("evidenceStatus", "insufficient"),
        )


def buildCorrectedQuery(queryText: str) -> str | None:
    """Return a material spelling correction candidate while preserving the original query."""
    normalizedWords = queryText.split()
    correctedWords: list[str] = []
    isMaterialCorrection = False
    for word in normalizedWords:
        strippedWord = re.sub(r"[^a-zA-Z]", "", word).lower()
        if len(strippedWord) < 5:
            correctedWords.append(word)
            continue
        matches = get_close_matches(strippedWord, SPELLING_LEXICON, n=1, cutoff=0.82)
        if matches and matches[0] != strippedWord:
            correctedWords.append(word.lower().replace(strippedWord, matches[0]))
            isMaterialCorrection = True
        else:
            correctedWords.append(word)
    if not isMaterialCorrection:
        return None
    return " ".join(correctedWords)


def buildFocusedRetrievalQuery(queryText: str) -> str | None:
    """Retry retrieval with the strongest remaining terms when the full query misses."""
    normalizedTokens = TOKEN_PATTERN.findall(queryText.lower())
    focusedTokens = [
        token for token in normalizedTokens if token not in LEXICAL_NOISE_WORDS and len(token) >= 5
    ]
    if not focusedTokens:
        return None
    focusedQuery = " ".join(focusedTokens[:3])
    if focusedQuery == queryText.lower():
        return None
    return focusedQuery


def extractNumericValues(retrievedChunks: list[RetrievedChunk]) -> list[float]:
    """Extract numeric values from evidence used by retrieve-then-compute routes."""
    extractedValues: list[float] = []
    for chunk in retrievedChunks[:3]:
        extractedValues.extend(float(value) for value in NUMBER_PATTERN.findall(chunk.content))
    return extractedValues


def buildCitations(retrievedChunks: list[RetrievedChunk]) -> list[CitationSchema]:
    """Map supporting evidence chunks into citation rows."""
    citationRows: list[CitationSchema] = []
    for citationIndex, chunk in enumerate(retrievedChunks, start=1):
        citationRows.append(
            CitationSchema(
                citationId=f"C{citationIndex}",
                documentTitle=chunk.documentTitle,
                documentVersion=chunk.documentVersion,
                chunkId=chunk.chunkId,
                structuralLocator=chunk.structuralLocator,
                exactSpan=chunk.content,
                supportScore=round(chunk.supportScore, 4),
            )
        )
    return citationRows


def hasConflictingEvidence(retrievedChunks: list[RetrievedChunk]) -> bool:
    """Detect a simple conflict signature for mutually incompatible evidence rows."""
    if len(retrievedChunks) < 2:
        return False
    topChunk = retrievedChunks[0]
    secondChunk = retrievedChunks[1]
    if abs(topChunk.supportScore - secondChunk.supportScore) > 0.08:
        return False
    topNumbers = set(NUMBER_PATTERN.findall(topChunk.content))
    secondNumbers = set(NUMBER_PATTERN.findall(secondChunk.content))
    return bool(topNumbers and secondNumbers and topNumbers != secondNumbers)

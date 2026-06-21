"""Persisted pipeline lifecycle services for developer control-plane governance."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from cortex.config import Settings
from cortex.domain.pipeline import (
    ComponentCapability,
    PipelineDefinition,
    PipelineEdge,
    PipelineNode,
)
from cortex.errors import InputValidationError
from cortex.models import PipelineVersion
from cortex.schemas import (
    PipelineGraphResponse,
    PipelineNodeSchema,
    PipelineVersionSummaryResponse,
)
from cortex.services.audit import persistControlPlaneAudit
from cortex.services.auth import IdentityContext


class PipelineService:
    """Coordinate immutable pipeline versions, validation, activation, and rollback."""

    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        if session is None:
            raise ValueError("session is required")
        self.session = session
        self.settings = settings

    async def getOrCreateActivePipeline(self, identity: IdentityContext) -> PipelineGraphResponse:
        """Return the active pipeline, bootstrapping the default definition once per enterprise."""
        activeVersion = await self._getActiveVersion(identity.enterpriseId)
        if activeVersion is None:
            activeVersion = await self._bootstrapDefaultPipeline(identity)
        return self._toPipelineGraph(activeVersion)

    async def listPipelineVersions(
        self,
        enterpriseId: UUID,
    ) -> list[PipelineVersionSummaryResponse]:
        """Return persisted immutable pipeline versions in newest-first order."""
        result = await self.session.execute(
            select(PipelineVersion)
            .where(PipelineVersion.enterpriseId == enterpriseId)
            .order_by(PipelineVersion.version.desc())
        )
        pipelineVersions = result.scalars().all()
        return [self._toVersionSummary(pipelineVersion) for pipelineVersion in pipelineVersions]

    async def validateNextPipeline(self, identity: IdentityContext) -> PipelineGraphResponse:
        """Create or reuse the next draft version and move it into the validated state."""
        draftVersion = await self._getLatestVersionByStatus(identity.enterpriseId, "draft")
        if draftVersion is None:
            draftVersion = await self._getLatestVersion(identity.enterpriseId)
            if draftVersion is None:
                draftVersion = await self._bootstrapDefaultPipeline(identity)
        definition = PipelineDefinition.model_validate(draftVersion.definition)
        definitionHash = definition.calculateDefinitionHash()
        draftVersion.definition = definition.model_dump(mode="json")
        draftVersion.definitionHash = definitionHash
        if draftVersion.status == "draft":
            draftVersion.status = "validated"
        await persistControlPlaneAudit(
            session=self.session,
            settings=self.settings,
            enterpriseId=identity.enterpriseId,
            actorId=identity.actorId,
            action="pipeline.validate",
            scope={"enterpriseId": str(identity.enterpriseId), "version": draftVersion.version},
            outcome="validated" if draftVersion.status == "validated" else draftVersion.status,
            pipelineVersion=draftVersion.version,
            eventPayload={
                "definitionHash": definitionHash.hex(),
                "rerankTopK": definition.rerankTopK,
            },
        )
        await self.session.commit()
        await self.session.refresh(draftVersion)
        return self._toPipelineGraph(draftVersion)

    async def activatePipeline(
        self,
        *,
        identity: IdentityContext,
        version: int | None = None,
    ) -> PipelineGraphResponse:
        """Promote a validated pipeline version to active and retire the previous active version."""
        targetVersion = await self._resolveActivationTarget(identity.enterpriseId, version)
        if targetVersion.status not in {"validated", "approved", "active"}:
            raise InputValidationError(
                "only validated or active pipeline versions can be activated"
            )
        activeVersion = await self._getActiveVersion(identity.enterpriseId)
        activationTime = datetime.now(UTC)
        if activeVersion is not None and activeVersion.id != targetVersion.id:
            activeVersion.status = "retired"
        targetVersion.status = "active"
        targetVersion.activatedAt = activationTime
        await persistControlPlaneAudit(
            session=self.session,
            settings=self.settings,
            enterpriseId=identity.enterpriseId,
            actorId=identity.actorId,
            action="pipeline.activate",
            scope={"enterpriseId": str(identity.enterpriseId), "version": targetVersion.version},
            outcome="active",
            pipelineVersion=targetVersion.version,
            eventPayload={
                "previousVersion": activeVersion.version if activeVersion is not None else None,
                "activatedAt": activationTime.isoformat(),
            },
        )
        await self.session.commit()
        await self.session.refresh(targetVersion)
        return self._toPipelineGraph(targetVersion)

    async def _bootstrapDefaultPipeline(self, identity: IdentityContext) -> PipelineVersion:
        definition = buildDefaultPipelineDefinition(
            pipelineVersion=self.settings.pipelineVersion,
            generatorModel=self.settings.generatorModel,
            rerankTopK=self.settings.rerankTopK,
        )
        createdAt = datetime.now(UTC)
        await self.session.execute(
            text(
                """
                INSERT INTO enterprise (id, name)
                VALUES (:enterprise_id, 'Cortex Enterprise')
                ON CONFLICT (id) DO NOTHING
                """
            ),
            {"enterprise_id": identity.enterpriseId},
        )
        pipelineVersion = PipelineVersion(
            id=uuid4(),
            enterpriseId=identity.enterpriseId,
            version=self.settings.pipelineVersion,
            status="active",
            definition=definition.model_dump(mode="json"),
            definitionHash=definition.calculateDefinitionHash(),
            createdBy=identity.actorId,
            createdAt=createdAt,
            activatedAt=createdAt,
        )
        self.session.add(pipelineVersion)
        await persistControlPlaneAudit(
            session=self.session,
            settings=self.settings,
            enterpriseId=identity.enterpriseId,
            actorId=identity.actorId,
            action="pipeline.bootstrap",
            scope={"enterpriseId": str(identity.enterpriseId), "version": pipelineVersion.version},
            outcome="active",
            pipelineVersion=pipelineVersion.version,
            eventPayload={"definitionHash": pipelineVersion.definitionHash.hex()},
            createdAt=createdAt,
        )
        await self.session.commit()
        await self.session.refresh(pipelineVersion)
        return pipelineVersion

    async def _createNextDraft(self, identity: IdentityContext) -> PipelineVersion:
        latestVersion = await self._getLatestVersion(identity.enterpriseId)
        baseDefinition = (
            PipelineDefinition.model_validate(latestVersion.definition)
            if latestVersion is not None
            else buildDefaultPipelineDefinition(
                pipelineVersion=self.settings.pipelineVersion,
                generatorModel=self.settings.generatorModel,
                rerankTopK=self.settings.rerankTopK,
            )
        )
        nextVersionNumber = (latestVersion.version + 1) if latestVersion is not None else 1
        draftVersion = PipelineVersion(
            id=uuid4(),
            enterpriseId=identity.enterpriseId,
            version=nextVersionNumber,
            status="draft",
            definition=baseDefinition.model_dump(mode="json"),
            definitionHash=baseDefinition.calculateDefinitionHash(),
            createdBy=identity.actorId,
            createdAt=datetime.now(UTC),
            activatedAt=None,
        )
        self.session.add(draftVersion)
        await self.session.flush()
        return draftVersion

    async def _resolveActivationTarget(
        self,
        enterpriseId: UUID,
        version: int | None,
    ) -> PipelineVersion:
        if version is None:
            targetVersion = await self._getLatestVersionByStatus(enterpriseId, "validated")
            if targetVersion is None:
                targetVersion = await self._getActiveVersion(enterpriseId)
        else:
            result = await self.session.execute(
                select(PipelineVersion).where(
                    PipelineVersion.enterpriseId == enterpriseId,
                    PipelineVersion.version == version,
                )
            )
            targetVersion = result.scalar_one_or_none()
        if targetVersion is None:
            raise InputValidationError("pipeline version was not found")
        return targetVersion

    async def _getActiveVersion(self, enterpriseId: UUID) -> PipelineVersion | None:
        return await self._getLatestVersionByStatus(enterpriseId, "active")

    async def _getLatestVersion(self, enterpriseId: UUID) -> PipelineVersion | None:
        result = await self.session.execute(
            select(PipelineVersion)
            .where(PipelineVersion.enterpriseId == enterpriseId)
            .order_by(PipelineVersion.version.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def _getLatestVersionByStatus(
        self,
        enterpriseId: UUID,
        status: str,
    ) -> PipelineVersion | None:
        result = await self.session.execute(
            select(PipelineVersion)
            .where(
                PipelineVersion.enterpriseId == enterpriseId,
                PipelineVersion.status == status,
            )
            .order_by(PipelineVersion.version.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    def _toPipelineGraph(self, pipelineVersion: PipelineVersion) -> PipelineGraphResponse:
        definition = PipelineDefinition.model_validate(pipelineVersion.definition)
        nodeOrder = {node.id: index + 1 for index, node in enumerate(definition.nodes)}
        return PipelineGraphResponse(
            name=definition.name,
            version=pipelineVersion.version,
            status=pipelineVersion.status,
            rerankTopK=definition.rerankTopK,
            nodes=[
                PipelineNodeSchema(
                    id=node.id,
                    label=node.config.get("label", node.componentType),
                    category=node.componentType,
                    status="healthy",
                    version=node.componentVersion,
                    config={"required": bool(node.capabilities), "sequence": nodeOrder[node.id]},
                )
                for node in definition.nodes
            ],
            edges=[
                {"source": edge.sourceNodeId, "target": edge.targetNodeId}
                for edge in definition.edges
            ],
        )

    def _toVersionSummary(
        self,
        pipelineVersion: PipelineVersion,
    ) -> PipelineVersionSummaryResponse:
        definition = PipelineDefinition.model_validate(pipelineVersion.definition)
        return PipelineVersionSummaryResponse(
            pipelineVersionId=pipelineVersion.id,
            enterpriseId=pipelineVersion.enterpriseId,
            version=pipelineVersion.version,
            status=pipelineVersion.status,
            createdBy=pipelineVersion.createdBy,
            createdAt=pipelineVersion.createdAt.astimezone(UTC).isoformat(),
            activatedAt=(
                pipelineVersion.activatedAt.astimezone(UTC).isoformat()
                if pipelineVersion.activatedAt is not None
                else None
            ),
            rerankTopK=definition.rerankTopK,
            definitionHash=pipelineVersion.definitionHash.hex(),
        )


def buildDefaultPipelineDefinition(
    *,
    pipelineVersion: int,
    generatorModel: str,
    rerankTopK: int,
) -> PipelineDefinition:
    """Create the baseline immutable pipeline definition used for bootstrap and cloning."""
    return PipelineDefinition(
        name="Enterprise evidence pipeline",
        rerankTopK=rerankTopK,
        nodes=[
            PipelineNode(
                id="ingest",
                componentType="ingestion",
                componentVersion=f"{pipelineVersion}.1.0",
                capabilities={ComponentCapability.INGESTION},
                config={"label": "Ingest & Normalize"},
                inputSchema="cortex.source.v1",
                outputSchema="cortex.normalized-document.v1",
            ),
            PipelineNode(
                id="scope",
                componentType="security",
                componentVersion="1.0.0",
                capabilities={ComponentCapability.AUTHORIZATION},
                config={"label": "Access Scope"},
                inputSchema="cortex.query.v1",
                outputSchema="cortex.scoped-query.v1",
            ),
            PipelineNode(
                id="retrieval",
                componentType="retrieval",
                componentVersion="2.6.1",
                capabilities={ComponentCapability.RETRIEVAL},
                config={"label": "Hybrid Retrieval"},
                inputSchema="cortex.scoped-query.v1",
                outputSchema="cortex.retrieval-candidates.v1",
            ),
            PipelineNode(
                id="rerank",
                componentType="reranking",
                componentVersion=f"top-{rerankTopK}",
                capabilities={ComponentCapability.RERANKING},
                config={"label": "Cross-Encoder"},
                inputSchema="cortex.retrieval-candidates.v1",
                outputSchema="cortex.reranked-candidates.v1",
            ),
            PipelineNode(
                id="confidence",
                componentType="confidence",
                componentVersion="2.1.0",
                capabilities={ComponentCapability.PROVENANCE},
                config={"label": "Source Confidence"},
                inputSchema="cortex.reranked-candidates.v1",
                outputSchema="cortex.supported-evidence.v1",
            ),
            PipelineNode(
                id="generation",
                componentType="generation",
                componentVersion=generatorModel,
                capabilities={ComponentCapability.GENERATION},
                config={"label": "Bounded Generation"},
                inputSchema="cortex.supported-evidence.v1",
                outputSchema="cortex.atomic-claims.v1",
            ),
            PipelineNode(
                id="citations",
                componentType="validation",
                componentVersion="1.3.2",
                capabilities={ComponentCapability.AUDIT, ComponentCapability.CLAIM_VALIDATION},
                config={"label": "Claims & Citations"},
                inputSchema="cortex.atomic-claims.v1",
                outputSchema="cortex.validated-answer.v1",
            ),
        ],
        edges=[
            PipelineEdge(sourceNodeId="ingest", targetNodeId="scope"),
            PipelineEdge(sourceNodeId="scope", targetNodeId="retrieval"),
            PipelineEdge(sourceNodeId="retrieval", targetNodeId="rerank"),
            PipelineEdge(sourceNodeId="rerank", targetNodeId="confidence"),
            PipelineEdge(sourceNodeId="confidence", targetNodeId="generation"),
            PipelineEdge(sourceNodeId="generation", targetNodeId="citations"),
        ],
    )

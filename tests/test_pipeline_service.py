"""Pipeline service tests lock the immutable validation and rollback lifecycle in place."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from cortex.services.auth import IdentityContext
from cortex.services.pipelines import PipelineService, buildDefaultPipelineDefinition
from cortex.models import PipelineVersion


class FakeAsyncSession:
    """Provide the async session methods the pipeline service touches in these tests."""

    async def commit(self) -> None:
        """Pretend to commit without touching a database."""

    async def refresh(self, _instance: object) -> None:
        """Pretend to refresh without touching a database."""

    async def flush(self) -> None:
        """Pretend to flush without touching a database."""

    def add(self, _instance: object) -> None:
        """Accept added rows so draft creation can proceed in memory."""


def buildIdentity(enterpriseId: UUID) -> IdentityContext:
    """Create a deterministic admin identity for pipeline governance tests."""

    return IdentityContext(
        enterpriseId=enterpriseId,
        actorId="alex.rivera@example.com",
        subject="alex.rivera@example.com",
        email="alex.rivera@example.com",
        displayName="Alex Rivera",
        issuer="https://cortex.example.com",
        audience="cortex",
        groups=("group:platform-admins",),
        roles=("admin", "builder"),
    )


def buildPipelineVersion(
    *,
    enterpriseId: UUID,
    version: int,
    status: str,
    activatedAt: datetime | None,
) -> PipelineVersion:
    """Build one in-memory immutable pipeline version for service tests."""

    definition = buildDefaultPipelineDefinition(
        pipelineVersion=1,
        generatorModel="qwen3:8b",
        rerankTopK=40,
    )
    createdAt = datetime(2026, 6, 22, tzinfo=UTC)
    return PipelineVersion(
        id=uuid4(),
        enterpriseId=enterpriseId,
        version=version,
        status=status,
        definition=definition.model_dump(mode="json"),
        definitionHash=definition.calculateDefinitionHash(),
        createdBy="alex.rivera@example.com",
        createdAt=createdAt,
        activatedAt=activatedAt,
    )


@pytest.mark.asyncio
async def testValidateNextPipelineCreatesSeparateValidatedVersion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Validation should produce a new validated immutable version instead of mutating the active one."""

    enterpriseId = uuid4()
    identity = buildIdentity(enterpriseId)
    session = FakeAsyncSession()
    service = PipelineService(
        session=session,
        settings=SimpleNamespace(pipelineVersion=1, generatorModel="qwen3:8b", rerankTopK=40),
    )
    activeVersion = buildPipelineVersion(
        enterpriseId=enterpriseId,
        version=1,
        status="active",
        activatedAt=datetime(2026, 6, 22, tzinfo=UTC),
    )
    draftVersion = buildPipelineVersion(
        enterpriseId=enterpriseId,
        version=2,
        status="draft",
        activatedAt=None,
    )
    persistAudit = AsyncMock()

    monkeypatch.setattr(
        service,
        "_getLatestVersionByStatus",
        AsyncMock(side_effect=lambda currentEnterpriseId, status: None if status == "draft" else activeVersion),
    )
    monkeypatch.setattr(service, "_getLatestVersion", AsyncMock(return_value=activeVersion))
    monkeypatch.setattr(service, "_createNextDraft", AsyncMock(return_value=draftVersion))
    monkeypatch.setattr("cortex.services.pipelines.persistControlPlaneAudit", persistAudit)

    response = await service.validateNextPipeline(identity)

    assert activeVersion.status == "active"
    assert draftVersion.status == "validated"
    assert response.version == 2
    assert response.status == "validated"
    assert persistAudit.await_args.kwargs["outcome"] == "validated"
    assert persistAudit.await_args.kwargs["pipelineVersion"] == 2


@pytest.mark.asyncio
async def testActivatePipelineAllowsRollbackToRetiredVersion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Rollback should reactivate a retired immutable version and retire the current active version."""

    enterpriseId = uuid4()
    identity = buildIdentity(enterpriseId)
    session = FakeAsyncSession()
    service = PipelineService(
        session=session,
        settings=SimpleNamespace(pipelineVersion=1, generatorModel="qwen3:8b", rerankTopK=40),
    )
    activeVersion = buildPipelineVersion(
        enterpriseId=enterpriseId,
        version=2,
        status="active",
        activatedAt=datetime(2026, 6, 22, tzinfo=UTC),
    )
    retiredVersion = buildPipelineVersion(
        enterpriseId=enterpriseId,
        version=1,
        status="retired",
        activatedAt=datetime(2026, 6, 21, tzinfo=UTC),
    )
    persistAudit = AsyncMock()

    monkeypatch.setattr(service, "_resolveActivationTarget", AsyncMock(return_value=retiredVersion))
    monkeypatch.setattr(service, "_getActiveVersion", AsyncMock(return_value=activeVersion))
    monkeypatch.setattr("cortex.services.pipelines.persistControlPlaneAudit", persistAudit)

    response = await service.activatePipeline(identity=identity, version=1)

    assert activeVersion.status == "retired"
    assert retiredVersion.status == "active"
    assert response.version == 1
    assert response.status == "active"
    assert persistAudit.await_args.kwargs["eventPayload"]["rollback"] is True

"""Developer-facing source onboarding and source operations services."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from cortex.config import Settings
from cortex.errors import InputValidationError, ProviderOperationError
from cortex.schemas import (
    CreateUploadSourceResponse,
    CreateWebsiteSourceRequest,
    CreateWebsiteSourceResponse,
    JobStatusResponse,
    JobSummaryResponse,
    SourceDetailResponse,
    SourceSummaryResponse,
    SourceVersionResponse,
)
from cortex.services.ingestion import calculateSourceFingerprint, calculateVersionId, serializeJson
from cortex.services.jobs import DurableJobService
from cortex.services.object_storage import LocalObjectStorage


class SourceService:
    """Coordinate real source onboarding flows on top of the deterministic live stack."""

    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        objectStorage: LocalObjectStorage,
    ) -> None:
        if session is None:
            raise ValueError("session is required")
        self.session = session
        self.settings = settings
        self.objectStorage = objectStorage
        self.jobService = DurableJobService(session)

    async def createUploadSource(
        self,
        *,
        enterpriseId: UUID,
        actorId: str,
        displayName: str,
        versionLabel: str,
        principalIds: list[str],
        fileName: str,
        mimeType: str,
        content: bytes,
        documentId: UUID | None = None,
        sourceAuthority: float = 0.85,
        extractionQuality: float = 0.9,
        publishedAt: datetime | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> CreateUploadSourceResponse:
        """Persist one uploaded source blob, create its pending version, and queue ingestion."""
        self._validateActor(actorId)
        normalizedMimeType = self._validateMimeType(mimeType)
        normalizedDisplayName = self._validateDisplayName(displayName)
        normalizedPrincipalIds = self._normalizePrincipalIds(principalIds)
        if not content:
            raise InputValidationError("uploaded source content cannot be empty")
        if len(content) > self.settings.maxUploadBytes:
            raise InputValidationError("uploaded source exceeds the configured size limit")

        resolvedDocumentId = documentId or uuid4()
        rawHash = hashlib.sha256(content).digest()
        objectKey = self._buildBlobObjectKey(rawHash, fileName)
        sourceUri = f"upload://{enterpriseId}/{resolvedDocumentId}/{Path(fileName).name}"
        await self.objectStorage.putObject(objectKey, content)
        versionId = calculateVersionId(enterpriseId, resolvedDocumentId, rawHash, versionLabel)
        await self._upsertBlob(rawHash, objectKey, normalizedMimeType, len(content))
        await self._upsertPendingSource(
            enterpriseId=enterpriseId,
            actorId=actorId,
            documentId=resolvedDocumentId,
            displayName=normalizedDisplayName,
            documentTitle=normalizedDisplayName,
            sourceType="upload",
            sourceUri=sourceUri,
            sourceFingerprint=calculateSourceFingerprint(sourceUri),
            versionId=versionId,
            versionLabel=versionLabel,
            rawHash=rawHash,
            mimeType=normalizedMimeType,
            objectKey=objectKey,
            principalIds=normalizedPrincipalIds,
            sourceAuthority=sourceAuthority,
            extractionQuality=extractionQuality,
            publishedAt=publishedAt,
            metadata=metadata or {},
        )
        jobId = await self.jobService.enqueueSourceIngestionJob(
            {
                "actorId": actorId,
                "displayName": normalizedDisplayName,
                "documentId": str(resolvedDocumentId),
                "enterpriseId": str(enterpriseId),
                "extractionQuality": extractionQuality,
                "fileName": Path(fileName).name,
                "metadata": metadata or {},
                "mimeType": normalizedMimeType,
                "objectKey": objectKey,
                "principalIds": normalizedPrincipalIds,
                "publishedAt": publishedAt.isoformat() if publishedAt else None,
                "rawSha256": rawHash.hex(),
                "sourceAuthority": sourceAuthority,
                "sourceType": "upload",
                "sourceUri": sourceUri,
                "versionId": str(versionId),
                "versionLabel": versionLabel,
            }
        )
        return CreateUploadSourceResponse(
            jobId=jobId,
            documentId=resolvedDocumentId,
            documentVersionId=versionId,
            status="queued",
        )

    async def createWebsiteSource(
        self,
        request: CreateWebsiteSourceRequest,
        *,
        actorId: str,
    ) -> CreateWebsiteSourceResponse:
        """Fetch one allowlisted page, persist the snapshot, and queue deterministic ingestion."""
        self._validateActor(actorId)
        normalizedDisplayName = self._validateDisplayName(request.displayName)
        normalizedPrincipalIds = self._normalizePrincipalIds(request.principalIds)
        normalizedSourceUri = request.sourceUri.strip()
        normalizedHost = httpx.URL(normalizedSourceUri).host or ""
        if normalizedHost.lower() not in self.settings.websiteAllowlist:
            raise InputValidationError("website host is not in the configured allowlist")
        htmlBytes, resolvedMimeType = await self._fetchWebsiteSnapshot(normalizedSourceUri)
        resolvedDocumentId = request.documentId or uuid4()
        rawHash = hashlib.sha256(htmlBytes).digest()
        objectKey = self._buildBlobObjectKey(rawHash, "snapshot.html")
        await self.objectStorage.putObject(objectKey, htmlBytes)
        versionId = calculateVersionId(
            request.enterpriseId, resolvedDocumentId, rawHash, request.versionLabel
        )
        await self._upsertBlob(rawHash, objectKey, resolvedMimeType, len(htmlBytes))
        await self._upsertPendingSource(
            enterpriseId=request.enterpriseId,
            actorId=actorId,
            documentId=resolvedDocumentId,
            displayName=normalizedDisplayName,
            documentTitle=normalizedDisplayName,
            sourceType="website",
            sourceUri=normalizedSourceUri,
            sourceFingerprint=calculateSourceFingerprint(normalizedSourceUri),
            versionId=versionId,
            versionLabel=request.versionLabel,
            rawHash=rawHash,
            mimeType=resolvedMimeType,
            objectKey=objectKey,
            principalIds=normalizedPrincipalIds,
            sourceAuthority=request.sourceAuthority,
            extractionQuality=request.extractionQuality,
            publishedAt=parseOptionalIsoTimestamp(request.publishedAt),
            metadata=request.metadata,
        )
        jobId = await self.jobService.enqueueSourceIngestionJob(
            {
                "actorId": actorId,
                "displayName": normalizedDisplayName,
                "documentId": str(resolvedDocumentId),
                "enterpriseId": str(request.enterpriseId),
                "extractionQuality": request.extractionQuality,
                "fileName": "snapshot.html",
                "metadata": request.metadata,
                "mimeType": resolvedMimeType,
                "objectKey": objectKey,
                "principalIds": normalizedPrincipalIds,
                "publishedAt": request.publishedAt,
                "rawSha256": rawHash.hex(),
                "sourceAuthority": request.sourceAuthority,
                "sourceType": "website",
                "sourceUri": normalizedSourceUri,
                "versionId": str(versionId),
                "versionLabel": request.versionLabel,
            }
        )
        return CreateWebsiteSourceResponse(
            jobId=jobId,
            documentId=resolvedDocumentId,
            documentVersionId=versionId,
            status="queued",
        )

    async def listSources(self, enterpriseId: UUID) -> list[SourceSummaryResponse]:
        """Return the developer-facing source inventory with the latest version status."""
        result = await self.session.execute(
            text(
                """
                SELECT
                    d.id AS document_id,
                    d.display_name,
                    d.source_type,
                    d.source_uri,
                    d.created_by,
                    d.updated_at,
                    dv.version_label,
                    dv.ingestion_status,
                    dv.quarantine_status,
                    dv.malware_status,
                    dv.published_at,
                    dv.activated_at,
                    dv.acl_principals
                FROM document AS d
                LEFT JOIN LATERAL (
                    SELECT *
                    FROM document_version
                    WHERE document_id = d.id
                    ORDER BY created_at DESC
                    LIMIT 1
                ) AS dv ON TRUE
                WHERE d.enterprise_id = :enterprise_id
                ORDER BY d.updated_at DESC, d.display_name ASC
                """
            ),
            {"enterprise_id": enterpriseId},
        )
        return [
            SourceSummaryResponse(
                documentId=row["document_id"],
                displayName=row["display_name"],
                sourceType=row["source_type"],
                sourceUri=row["source_uri"],
                createdBy=row["created_by"],
                updatedAt=row["updated_at"].astimezone(UTC).isoformat(),
                latestVersionLabel=row["version_label"],
                latestIngestionStatus=row["ingestion_status"],
                latestQuarantineStatus=row["quarantine_status"],
                latestMalwareStatus=row["malware_status"],
                latestPublishedAt=_formatTimestamp(row["published_at"]),
                latestActivatedAt=_formatTimestamp(row["activated_at"]),
                principalIds=list(row["acl_principals"] or []),
            )
            for row in result.mappings()
        ]

    async def getSourceDetail(self, enterpriseId: UUID, documentId: UUID) -> SourceDetailResponse:
        """Return one source record and its version history for the developer console."""
        documentResult = await self.session.execute(
            text(
                """
                SELECT id, display_name, source_type, source_uri, created_by, updated_at, source_fingerprint
                FROM document
                WHERE enterprise_id = :enterprise_id AND id = :document_id
                """
            ),
            {"enterprise_id": enterpriseId, "document_id": documentId},
        )
        documentRow = documentResult.mappings().first()
        if documentRow is None:
            raise InputValidationError("source document was not found")
        versionResult = await self.session.execute(
            text(
                """
                SELECT
                    id,
                    version_label,
                    status,
                    ingestion_status,
                    quarantine_status,
                    malware_status,
                    mime_type,
                    parser_name,
                    parser_version,
                    object_key,
                    raw_hash,
                    canonical_hash,
                    source_authority,
                    published_at,
                    created_at,
                    activated_at,
                    failure_code,
                    failure_detail,
                    extraction_diagnostics,
                    accelerator_reports,
                    acl_principals
                FROM document_version
                WHERE enterprise_id = :enterprise_id AND document_id = :document_id
                ORDER BY created_at DESC
                """
            ),
            {"enterprise_id": enterpriseId, "document_id": documentId},
        )
        versions = [
            SourceVersionResponse(
                documentVersionId=row["id"],
                versionLabel=row["version_label"],
                status=row["status"],
                ingestionStatus=row["ingestion_status"],
                quarantineStatus=row["quarantine_status"],
                malwareStatus=row["malware_status"],
                mimeType=row["mime_type"],
                parserName=row["parser_name"],
                parserVersion=row["parser_version"],
                objectKey=row["object_key"],
                rawSha256=bytes(row["raw_hash"]).hex(),
                canonicalContentSha256=bytes(row["canonical_hash"]).hex(),
                sourceAuthority=row["source_authority"],
                publishedAt=_formatTimestamp(row["published_at"]),
                createdAt=row["created_at"].astimezone(UTC).isoformat(),
                activatedAt=_formatTimestamp(row["activated_at"]),
                failureCode=row["failure_code"],
                failureDetail=row["failure_detail"],
                extractionDiagnostics=row["extraction_diagnostics"] or {},
                acceleratorReports=list(row["accelerator_reports"] or []),
                principalIds=list(row["acl_principals"] or []),
            )
            for row in versionResult.mappings()
        ]
        return SourceDetailResponse(
            documentId=documentRow["id"],
            displayName=documentRow["display_name"],
            sourceType=documentRow["source_type"],
            sourceUri=documentRow["source_uri"],
            createdBy=documentRow["created_by"],
            updatedAt=documentRow["updated_at"].astimezone(UTC).isoformat(),
            sourceFingerprint=bytes(documentRow["source_fingerprint"]).hex(),
            versions=versions,
        )

    async def listJobs(self, enterpriseId: UUID) -> list[JobSummaryResponse]:
        """Return the newest durable jobs for the developer jobs panel."""
        result = await self.session.execute(
            text(
                """
                SELECT
                    id,
                    job_type,
                    status,
                    attempts,
                    updated_at,
                    last_error,
                    payload
                FROM durable_job
                WHERE enterprise_id = :enterprise_id
                ORDER BY updated_at DESC
                LIMIT 20
                """
            ),
            {"enterprise_id": enterpriseId},
        )
        return [
            JobSummaryResponse(
                jobId=row["id"],
                jobType=row["job_type"],
                status=row["status"],
                attempts=row["attempts"],
                updatedAt=row["updated_at"].astimezone(UTC).isoformat(),
                lastError=row["last_error"],
                documentId=_extractUuid(row["payload"], "documentId"),
                sourceDisplayName=(row["payload"] or {}).get("displayName"),
            )
            for row in result.mappings()
        ]

    async def getJobStatus(self, jobId: UUID) -> JobStatusResponse | None:
        """Return one durable job or ``None`` when it has not been queued."""
        result = await self.session.execute(
            text(
                """
                SELECT
                    id,
                    enterprise_id,
                    job_type,
                    status,
                    attempts,
                    available_at,
                    locked_at,
                    last_error,
                    payload
                FROM durable_job
                WHERE id = :job_id
                """
            ),
            {"job_id": jobId},
        )
        row = result.mappings().first()
        if row is None:
            return None
        payload = row["payload"] or {}
        return JobStatusResponse(
            jobId=row["id"],
            enterpriseId=row["enterprise_id"],
            jobType=row["job_type"],
            status=row["status"],
            attempts=row["attempts"],
            availableAt=row["available_at"].astimezone(UTC).isoformat(),
            lockedAt=_formatTimestamp(row["locked_at"]),
            updatedAt=row["updated_at"].astimezone(UTC).isoformat(),
            lastError=row["last_error"],
            documentId=_extractUuid(payload, "documentId"),
            documentVersionId=_extractUuid(payload, "versionId"),
            sourceDisplayName=payload.get("displayName"),
        )

    async def _upsertBlob(
        self,
        rawHash: bytes,
        objectKey: str,
        mimeType: str,
        sizeBytes: int,
    ) -> None:
        try:
            await self.session.execute(
                text(
                    """
                    INSERT INTO source_blob (raw_hash, object_key, mime_type, size_bytes)
                    VALUES (:raw_hash, :object_key, :mime_type, :size_bytes)
                    ON CONFLICT (raw_hash) DO UPDATE SET
                        object_key = EXCLUDED.object_key,
                        mime_type = EXCLUDED.mime_type,
                        size_bytes = EXCLUDED.size_bytes
                    """
                ),
                {
                    "raw_hash": rawHash,
                    "object_key": objectKey,
                    "mime_type": mimeType,
                    "size_bytes": sizeBytes,
                },
            )
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise

    async def _upsertPendingSource(
        self,
        *,
        enterpriseId: UUID,
        actorId: str,
        documentId: UUID,
        displayName: str,
        documentTitle: str,
        sourceType: str,
        sourceUri: str,
        sourceFingerprint: bytes,
        versionId: UUID,
        versionLabel: str,
        rawHash: bytes,
        mimeType: str,
        objectKey: str,
        principalIds: list[str],
        sourceAuthority: float,
        extractionQuality: float,
        publishedAt: datetime | None,
        metadata: dict[str, Any],
    ) -> None:
        extractionDiagnostics = {
            "bytesStored": metadata.get("bytesStored"),
            "extractionQuality": extractionQuality,
            "metadataKeys": sorted(metadata),
        }
        try:
            await self.session.execute(
                text(
                    """
                    INSERT INTO enterprise (id, name)
                    VALUES (:enterprise_id, 'Cortex Enterprise')
                    ON CONFLICT (id) DO NOTHING
                    """
                ),
                {"enterprise_id": enterpriseId},
            )
            await self.session.execute(
                text(
                    """
                    INSERT INTO document (
                        id, enterprise_id, title, display_name, source_type, source_uri,
                        source_fingerprint, metadata, created_by, updated_at
                    ) VALUES (
                        :document_id, :enterprise_id, :title, :display_name, :source_type,
                        :source_uri, :source_fingerprint, CAST(:metadata AS jsonb),
                        :created_by, now()
                    )
                    ON CONFLICT (id) DO UPDATE SET
                        title = EXCLUDED.title,
                        display_name = EXCLUDED.display_name,
                        source_type = EXCLUDED.source_type,
                        source_uri = EXCLUDED.source_uri,
                        source_fingerprint = EXCLUDED.source_fingerprint,
                        metadata = EXCLUDED.metadata,
                        updated_at = now()
                    """
                ),
                {
                    "document_id": documentId,
                    "enterprise_id": enterpriseId,
                    "title": documentTitle,
                    "display_name": displayName,
                    "source_type": sourceType,
                    "source_uri": sourceUri,
                    "source_fingerprint": sourceFingerprint,
                    "metadata": serializeJson(metadata),
                    "created_by": actorId,
                },
            )
            await self.session.execute(
                text(
                    """
                    INSERT INTO document_version (
                        id, enterprise_id, document_id, acl_principals, version_hash,
                        version_label, raw_hash, canonical_hash, mime_type, object_key,
                        parser_name, parser_version, source_authority, published_at, status,
                        ingestion_status, quarantine_status, malware_status,
                        extraction_diagnostics, accelerator_reports, failure_code, failure_detail
                    ) VALUES (
                        :version_id, :enterprise_id, :document_id, CAST(:acl_principals AS jsonb),
                        :version_hash, :version_label, :raw_hash, :canonical_hash, :mime_type,
                        :object_key, 'pending', 'pending', :source_authority, :published_at,
                        'processing', 'queued', 'clear', 'pending',
                        CAST(:extraction_diagnostics AS jsonb), '[]'::jsonb, NULL, NULL
                    )
                    ON CONFLICT (id) DO UPDATE SET
                        acl_principals = EXCLUDED.acl_principals,
                        version_hash = EXCLUDED.version_hash,
                        version_label = EXCLUDED.version_label,
                        raw_hash = EXCLUDED.raw_hash,
                        canonical_hash = EXCLUDED.canonical_hash,
                        mime_type = EXCLUDED.mime_type,
                        object_key = EXCLUDED.object_key,
                        source_authority = EXCLUDED.source_authority,
                        published_at = EXCLUDED.published_at,
                        ingestion_status = 'queued',
                        quarantine_status = 'clear',
                        malware_status = 'pending',
                        extraction_diagnostics = EXCLUDED.extraction_diagnostics,
                        failure_code = NULL,
                        failure_detail = NULL
                    """
                ),
                {
                    "version_id": versionId,
                    "enterprise_id": enterpriseId,
                    "document_id": documentId,
                    "acl_principals": serializeJson(principalIds),
                    "version_hash": rawHash,
                    "version_label": versionLabel,
                    "raw_hash": rawHash,
                    "canonical_hash": rawHash,
                    "mime_type": mimeType,
                    "object_key": objectKey,
                    "source_authority": sourceAuthority,
                    "published_at": publishedAt,
                    "extraction_diagnostics": serializeJson(extractionDiagnostics),
                },
            )
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise

    async def _fetchWebsiteSnapshot(self, sourceUri: str) -> tuple[bytes, str]:
        """Fetch one allowlisted page without following the crawl boundary into discovery."""
        try:
            async with httpx.AsyncClient(timeout=self.settings.sourceFetchTimeoutSeconds) as client:
                response = await client.get(sourceUri, follow_redirects=True)
                response.raise_for_status()
        except Exception as error:
            raise ProviderOperationError(f"failed to fetch website source: {sourceUri}") from error
        contentType = response.headers.get("content-type", "text/html").split(";", maxsplit=1)[0]
        normalizedMimeType = self._validateMimeType(contentType)
        return response.content, normalizedMimeType

    def _validateMimeType(self, mimeType: str) -> str:
        """Ensure source onboarding only accepts explicit enterprise-approved formats."""
        normalizedMimeType = mimeType.strip().lower()
        if normalizedMimeType not in self.settings.allowedUploadMimeTypes:
            raise InputValidationError("source MIME type is not allowlisted")
        return normalizedMimeType

    def _normalizePrincipalIds(self, principalIds: list[str]) -> list[str]:
        """Normalize ACL principals without widening access during source creation."""
        normalizedPrincipalIds = list(
            dict.fromkeys(
                principalId.strip() for principalId in principalIds if principalId.strip()
            )
        )
        if not normalizedPrincipalIds:
            raise InputValidationError("at least one ACL principal is required")
        return normalizedPrincipalIds

    def _validateActor(self, actorId: str) -> None:
        """Reject empty actor identities so audit metadata stays attributable."""
        if not actorId.strip():
            raise InputValidationError("actorId cannot be empty")

    def _validateDisplayName(self, displayName: str) -> str:
        """Normalize UI-provided names before they become source records."""
        normalizedDisplayName = displayName.strip()
        if not normalizedDisplayName:
            raise InputValidationError("displayName cannot be empty")
        return normalizedDisplayName

    def _buildBlobObjectKey(self, rawHash: bytes, fileName: str) -> str:
        """Derive a stable object key so identical raw bytes reuse the same storage path."""
        suffix = Path(fileName).suffix.lower()
        return f"blobs/sha256/{rawHash.hex()}{suffix}"


def parseOptionalIsoTimestamp(timestampValue: str | None) -> datetime | None:
    """Parse optional timestamps supplied through source onboarding endpoints."""
    if timestampValue is None:
        return None
    return datetime.fromisoformat(timestampValue.replace("Z", "+00:00")).astimezone(UTC)


def _formatTimestamp(timestampValue: datetime | None) -> str | None:
    """Serialize timestamps consistently for UI contracts."""
    if timestampValue is None:
        return None
    return timestampValue.astimezone(UTC).isoformat()


def _extractUuid(payload: dict[str, Any], key: str) -> UUID | None:
    """Parse a UUID from job payload metadata without hiding malformed state."""
    rawValue = payload.get(key)
    if rawValue is None:
        return None
    return UUID(str(rawValue))

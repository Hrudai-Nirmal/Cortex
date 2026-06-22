"""Validated runtime settings shared by the API and worker processes."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse
from uuid import UUID

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _toUpperSnakeCase(fieldName: str) -> str:
    """Convert internal camelCase settings fields into stable environment aliases."""
    if not fieldName:
        raise ValueError("fieldName cannot be empty")
    characters: list[str] = []
    for index, character in enumerate(fieldName):
        if character.isupper() and index > 0 and not fieldName[index - 1].isupper():
            characters.append("_")
        characters.append(character.upper())
    return f"CORTEX_{''.join(characters)}"


class Settings(BaseSettings):
    """Describe the deployable Cortex runtime profile."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="",
        case_sensitive=False,
        extra="ignore",
        alias_generator=_toUpperSnakeCase,
        populate_by_name=True,
    )

    environment: Literal["development", "test", "production"] = "development"
    authMode: Literal["fixture"] = "fixture"
    databaseUrl: str = "postgresql+asyncpg://cortex:cortex@127.0.0.1:5432/cortex"
    enterpriseId: UUID = UUID("00000000-0000-0000-0000-000000000001")
    devMode: bool = True
    requiredAccelerator: Literal["auto", "cpu", "mps", "cuda"] = "mps"
    oidcIssuerUrl: str = "https://cortex.local/oidc"
    oidcAudience: str = "cortex"
    ollamaBaseUrl: str = "http://127.0.0.1:11434"
    allowRemoteModelEndpoint: bool = False
    generatorModel: str = "qwen3:14b"
    embeddingModel: str = "qwen3-embedding:0.6b"
    packagePyTorchWheelIndexUrl: str = "https://download.pytorch.org/whl/cpu"
    packagePyTorchPreinstall: str = "torch torchvision"
    objectStorageRoot: str = ".cortex-data/object-storage"
    consoleHost: str = "127.0.0.1"
    queryHost: str = "127.0.0.1"
    consolePublicUrl: str = "http://127.0.0.1:5173"
    queryPublicUrl: str = "http://127.0.0.1:5174"
    pipelineVersion: int = Field(default=3, ge=1)
    retrievalCandidateLimit: int = Field(default=120, ge=20, le=500)
    rerankTopK: int = Field(default=40, ge=30, le=50)
    sourceConfidenceThreshold: float = Field(default=0.58, ge=0.0, le=1.0)
    queryContentRetentionDays: int = Field(default=30, ge=1)
    traceRetentionDays: int = Field(default=90, ge=1)
    auditRetentionDays: int = Field(default=365, ge=1)
    maxUploadBytes: int = Field(default=50 * 1024 * 1024, ge=1024)
    sourceFetchTimeoutSeconds: float = Field(default=10.0, ge=1.0, le=60.0)
    workerPollIntervalSeconds: float = Field(default=1.0, ge=0.1, le=30.0)
    seedPrincipalIds: tuple[str, ...] = ("group:employees", "role:builder", "role:auditor")
    websiteAllowlist: tuple[str, ...] = ("127.0.0.1", "localhost")
    allowedUploadMimeTypes: tuple[str, ...] = (
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "text/html",
        "text/plain",
        "text/markdown",
        "text/csv",
    )

    @field_validator(
        "databaseUrl",
        "oidcIssuerUrl",
        "oidcAudience",
        "ollamaBaseUrl",
        "generatorModel",
        "embeddingModel",
        "packagePyTorchWheelIndexUrl",
        "packagePyTorchPreinstall",
        "objectStorageRoot",
        "consolePublicUrl",
        "queryPublicUrl",
    )
    @classmethod
    def validateNonEmptyValue(cls, value: str) -> str:
        """Reject empty infrastructure identifiers at process startup."""
        normalizedValue = value.strip()
        if not normalizedValue:
            raise ValueError("configuration value cannot be empty")
        return normalizedValue

    @field_validator("websiteAllowlist")
    @classmethod
    def validateNormalizedSequence(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        """Normalize configured string tuples so runtime checks stay deterministic."""
        normalizedValues = tuple(value.strip().lower() for value in values if value.strip())
        return normalizedValues

    @field_validator("allowedUploadMimeTypes")
    @classmethod
    def validateAllowedMimeTypes(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        """Require at least one accepted MIME type for upload onboarding."""
        normalizedValues = cls.validateNormalizedSequence(values)
        if not normalizedValues:
            raise ValueError("allowedUploadMimeTypes cannot be empty")
        return normalizedValues

    @field_validator("consoleHost", "queryHost")
    @classmethod
    def validateHostName(cls, value: str) -> str:
        """Keep host-only settings free of schemes, ports, and paths."""
        normalizedValue = value.strip().lower()
        if not normalizedValue:
            raise ValueError("host cannot be empty")
        if "://" in normalizedValue or "/" in normalizedValue or "?" in normalizedValue:
            raise ValueError("host must not include a scheme, path, or query string")
        if ":" in normalizedValue and not normalizedValue.startswith("["):
            raise ValueError("host must not include a port")
        return normalizedValue

    @model_validator(mode="after")
    def validateDeploymentProfile(self) -> Settings:
        """Enforce deployment-critical domain and storage invariants before startup."""
        consolePublicHost = self._parseUrlHost(self.consolePublicUrl, "consolePublicUrl")
        queryPublicHost = self._parseUrlHost(self.queryPublicUrl, "queryPublicUrl")
        if consolePublicHost != self.consoleHost:
            raise ValueError("consolePublicUrl host must match consoleHost")
        if queryPublicHost != self.queryHost:
            raise ValueError("queryPublicUrl host must match queryHost")
        if self.environment == "production":
            if self.consoleHost == self.queryHost:
                raise ValueError("production requires distinct consoleHost and queryHost values")
            if consolePublicHost in {"127.0.0.1", "localhost"} or queryPublicHost in {
                "127.0.0.1",
                "localhost",
            }:
                raise ValueError("production public URLs must not use localhost origins")
            if not Path(self.objectStorageRoot).is_absolute():
                raise ValueError("production objectStorageRoot must be an absolute path")
        return self

    def getCorsOrigins(self) -> tuple[str, ...]:
        """Return browser origins allowed to call the API from split Cortex surfaces."""
        origins = [self._normalizeOrigin(self.consolePublicUrl), self._normalizeOrigin(self.queryPublicUrl)]
        if self.environment != "production":
            origins.extend(
                [
                    "http://127.0.0.1:5173",
                    "http://localhost:5173",
                    "http://127.0.0.1:5174",
                    "http://localhost:5174",
                ]
            )
        return tuple(dict.fromkeys(origins))

    @staticmethod
    def _parseUrlHost(urlValue: str, fieldName: str) -> str:
        """Extract a host from one public URL and reject unusable values early."""
        parsedUrl = urlparse(urlValue)
        if parsedUrl.scheme not in {"http", "https"} or not parsedUrl.hostname:
            raise ValueError(f"{fieldName} must be an absolute http(s) URL")
        return parsedUrl.hostname.lower()

    @staticmethod
    def _normalizeOrigin(urlValue: str) -> str:
        """Convert a configured public URL into the browser origin used for CORS."""
        parsedUrl = urlparse(urlValue)
        portSegment = f":{parsedUrl.port}" if parsedUrl.port is not None else ""
        return f"{parsedUrl.scheme}://{parsedUrl.hostname}{portSegment}"


@lru_cache(maxsize=1)
def getSettings() -> Settings:
    """Return one validated settings object per process."""
    return Settings()

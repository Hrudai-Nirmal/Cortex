"""Runtime health checks for the local live-integration development profile."""

from __future__ import annotations

from ipaddress import ip_address
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from cortex.config import Settings
from cortex.schemas import RuntimeComponentSchema, RuntimeHealthResponse
from cortex.services.accelerator import detectAvailableAccelerator
from cortex.services.model_provider import OllamaModelProvider


class RuntimeHealthService:
    """Check the required local dependencies without mutating application state."""

    def __init__(
        self,
        session: AsyncSession | None,
        settings: Settings,
        modelProvider: OllamaModelProvider,
    ) -> None:
        self.session = session
        self.settings = settings
        self.modelProvider = modelProvider

    async def getReadiness(self) -> RuntimeHealthResponse:
        """Aggregate database, local model, object storage, and accelerator readiness."""
        components = [
            self._checkDeploymentConfig(),
            await self._checkDatabase(),
            await self._checkOllama(),
            self._checkModelEndpointPolicy(),
            self._checkObjectStorage(),
            self._checkAccelerator(),
            self._checkParserDependencies(),
            self._checkWebsiteIngestion(),
        ]
        status = (
            "ready" if all(component.status == "ready" for component in components) else "degraded"
        )
        return RuntimeHealthResponse(
            status=status,
            environment=self.settings.environment,
            components=components,
        )

    async def getStartupReadiness(self) -> RuntimeHealthResponse:
        """Expose static startup checks that do not require remote dependency round trips."""
        components = [
            self._checkDeploymentConfig(),
            self._checkModelEndpointPolicy(),
            self._checkObjectStorage(),
            self._checkAccelerator(),
            self._checkParserDependencies(),
            self._checkWebsiteIngestion(),
        ]
        status = (
            "ready" if all(component.status == "ready" for component in components) else "degraded"
        )
        return RuntimeHealthResponse(
            status=status,
            environment=self.settings.environment,
            components=components,
        )

    async def _checkDatabase(self) -> RuntimeComponentSchema:
        if self.session is None:
            return RuntimeComponentSchema(
                name="postgresql",
                status="unavailable",
                detail="database session is unavailable for readiness checks",
            )
        try:
            await self.session.execute(text("SELECT 1"))
            pgvectorInstalled = await self.session.scalar(
                text("SELECT extname FROM pg_extension WHERE extname = 'vector'")
            )
        except Exception as error:
            return RuntimeComponentSchema(
                name="postgresql",
                status="unavailable",
                detail=str(error),
            )
        if pgvectorInstalled != "vector":
            return RuntimeComponentSchema(
                name="postgresql",
                status="degraded",
                detail="database ready but pgvector extension is missing",
            )
        return RuntimeComponentSchema(name="postgresql", status="ready", detail="database ready")

    async def _checkOllama(self) -> RuntimeComponentSchema:
        isReady, detail = await self.modelProvider.checkHealth()
        return RuntimeComponentSchema(
            name="ollama",
            status="ready" if isReady else "unavailable",
            detail=detail,
        )

    def _checkObjectStorage(self) -> RuntimeComponentSchema:
        storageRoot = Path(self.settings.objectStorageRoot)
        try:
            storageRoot.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            return RuntimeComponentSchema(
                name="object-storage",
                status="unavailable",
                detail=str(error),
            )
        return RuntimeComponentSchema(
            name="object-storage",
            status="ready",
            detail=str(storageRoot.resolve()),
        )

    def _checkDeploymentConfig(self) -> RuntimeComponentSchema:
        """Show operators the host split and browser origins the package expects."""
        detail = (
            f"console={self.settings.consolePublicUrl}, query={self.settings.queryPublicUrl}, "
            f"cors={', '.join(self.settings.getCorsOrigins())}"
        )
        return RuntimeComponentSchema(
            name="deployment-config",
            status="ready",
            detail=detail,
        )

    def _checkModelEndpointPolicy(self) -> RuntimeComponentSchema:
        """Guard the offline-capable default by flagging remote model endpoints explicitly."""
        modelHost = self.modelProvider.getBaseHost()
        if self.settings.allowRemoteModelEndpoint:
            return RuntimeComponentSchema(
                name="model-endpoint-policy",
                status="ready",
                detail=f"remote model endpoints permitted ({modelHost})",
            )
        if self._isInternalHost(modelHost):
            return RuntimeComponentSchema(
                name="model-endpoint-policy",
                status="ready",
                detail=f"offline-capable endpoint host {modelHost}",
            )
        return RuntimeComponentSchema(
            name="model-endpoint-policy",
            status="degraded",
            detail=(
                f"model endpoint host {modelHost} is not local or private; set "
                "CORTEX_ALLOW_REMOTE_MODEL_ENDPOINT=true only when this is intentional"
            ),
        )

    def _checkAccelerator(self) -> RuntimeComponentSchema:
        actualAccelerator = detectAvailableAccelerator()
        if self.settings.requiredAccelerator not in {"auto", actualAccelerator}:
            return RuntimeComponentSchema(
                name="accelerator",
                status="degraded",
                detail=(
                    f"required {self.settings.requiredAccelerator}, detected {actualAccelerator}"
                ),
            )
        return RuntimeComponentSchema(
            name="accelerator",
            status="ready",
            detail=f"detected {actualAccelerator}",
        )

    def _checkParserDependencies(self) -> RuntimeComponentSchema:
        """Confirm the local parser toolchain is available for source onboarding."""
        try:
            import docling  # noqa: F401
        except ImportError as error:
            return RuntimeComponentSchema(
                name="parser-dependencies",
                status="degraded",
                detail=f"Docling unavailable: {error}",
            )
        return RuntimeComponentSchema(
            name="parser-dependencies",
            status="ready",
            detail="Docling and local parsers available",
        )

    def _checkWebsiteIngestion(self) -> RuntimeComponentSchema:
        """Expose the configured single-page website-ingestion boundary to operators."""
        if not self.settings.websiteAllowlist:
            return RuntimeComponentSchema(
                name="website-ingestion",
                status="degraded",
                detail="website allowlist is empty",
            )
        return RuntimeComponentSchema(
            name="website-ingestion",
            status="ready",
            detail=", ".join(self.settings.websiteAllowlist),
        )

    @staticmethod
    def _isInternalHost(hostname: str) -> bool:
        """Treat loopback, private IPs, and simple internal DNS names as offline-capable."""
        normalizedHost = hostname.strip().lower()
        if not normalizedHost:
            return False
        if normalizedHost in {"localhost", "ollama"} or normalizedHost.endswith(
            (".local", ".internal")
        ):
            return True
        try:
            return ip_address(normalizedHost).is_private or ip_address(normalizedHost).is_loopback
        except ValueError:
            parsedHost = urlparse(f"http://{normalizedHost}").hostname or ""
            return "." not in parsedHost

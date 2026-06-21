"""Runtime health checks for the local live-integration development profile."""

from __future__ import annotations

from pathlib import Path

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
        session: AsyncSession,
        settings: Settings,
        modelProvider: OllamaModelProvider,
    ) -> None:
        if session is None:
            raise ValueError("session is required")
        self.session = session
        self.settings = settings
        self.modelProvider = modelProvider

    async def getReadiness(self) -> RuntimeHealthResponse:
        """Aggregate database, local model, object storage, and accelerator readiness."""
        components = [
            await self._checkDatabase(),
            await self._checkOllama(),
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
        try:
            await self.session.execute(text("SELECT 1"))
        except Exception as error:
            return RuntimeComponentSchema(
                name="postgresql",
                status="unavailable",
                detail=str(error),
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

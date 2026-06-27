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
            self._checkIdentityProfile(),
            self._checkModelProfile(),
            self._checkPackageBuildProfile(),
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
            self._checkIdentityProfile(),
            self._checkModelProfile(),
            self._checkPackageBuildProfile(),
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
            return self._buildComponent(
                name="postgresql",
                status="unavailable",
                severity="error",
                detail="database session is unavailable for readiness checks",
                remediation=(
                    "Run live readiness checks with a real database session before promoting "
                    "the package or starting the worker."
                ),
            )
        try:
            await self.session.execute(text("SELECT 1"))
            pgvectorInstalled = await self.session.scalar(
                text("SELECT extname FROM pg_extension WHERE extname = 'vector'")
            )
        except Exception as error:
            return self._buildComponent(
                name="postgresql",
                status="unavailable",
                severity="error",
                detail=str(error),
                remediation=(
                    "Confirm CORTEX_DATABASE_URL reaches PostgreSQL, the service is running, "
                    "and the migration job completed successfully."
                ),
            )
        if pgvectorInstalled != "vector":
            return self._buildComponent(
                name="postgresql",
                status="degraded",
                severity="error",
                detail="database ready but pgvector extension is missing",
                remediation=(
                    "Install or enable the PostgreSQL vector extension, then rerun Cortex "
                    "migrations before accepting retrieval traffic."
                ),
            )
        return self._buildComponent(
            name="postgresql",
            status="ready",
            severity="info",
            detail="database ready",
        )

    async def _checkOllama(self) -> RuntimeComponentSchema:
        isReady, detail = await self.modelProvider.checkHealth()
        remediation = None
        if not isReady:
            remediation = (
                "Start the configured model endpoint and verify CORTEX_OLLAMA_BASE_URL. "
                "If the endpoint is reachable but models are missing, run "
                "pnpm package:pull-models and then pnpm package:verify."
            )
        return self._buildComponent(
            name="ollama",
            status="ready" if isReady else "unavailable",
            severity="info" if isReady else "error",
            detail=detail,
            remediation=remediation,
        )

    def _checkObjectStorage(self) -> RuntimeComponentSchema:
        storageRoot = Path(self.settings.objectStorageRoot)
        probePath = storageRoot / ".cortex-write-probe"
        try:
            storageRoot.mkdir(parents=True, exist_ok=True)
            probePath.write_text("cortex-ready", encoding="utf-8")
            probePath.unlink()
        except OSError as error:
            return self._buildComponent(
                name="object-storage",
                status="unavailable",
                severity="error",
                detail=f"{storageRoot}: {error}",
                remediation=(
                    "Create the object-storage directory with read/write permissions for the "
                    "api and worker containers, and confirm the mounted persistent volume allows "
                    "Cortex to create and delete probe files."
                ),
            )
        return self._buildComponent(
            name="object-storage",
            status="ready",
            severity="info",
            detail=f"{storageRoot.resolve()} (read/write probe ok)",
        )

    def _checkDeploymentConfig(self) -> RuntimeComponentSchema:
        """Show operators the host split and browser origins the package expects."""
        startupPolicy = (
            "fail-closed"
            if self.settings.environment == "production" and not self.settings.devMode
            else "report-only"
        )
        detail = (
            f"console={self.settings.consolePublicUrl}, query={self.settings.queryPublicUrl}, "
            f"cors={', '.join(self.settings.getCorsOrigins())}, "
            f"startupPolicy={startupPolicy}, "
            f"querySurfaceMode={self.settings.querySurfaceMode}"
        )
        return self._buildComponent(
            name="deployment-config",
            status="ready",
            severity="info",
            detail=detail,
        )

    def _checkModelEndpointPolicy(self) -> RuntimeComponentSchema:
        """Guard the offline-capable default by flagging remote model endpoints explicitly."""
        modelHost = self.modelProvider.getBaseHost()
        if self.settings.allowRemoteModelEndpoint:
            return self._buildComponent(
                name="model-endpoint-policy",
                status="ready",
                severity="info",
                detail=f"remote model endpoints permitted ({modelHost})",
                remediation=(
                    "Keep this exception documented in the client deployment profile and "
                    "confirm the remote dependency is intentional."
                ),
            )
        if self._isInternalHost(modelHost):
            return self._buildComponent(
                name="model-endpoint-policy",
                status="ready",
                severity="info",
                detail=f"offline-capable endpoint host {modelHost}",
            )
        return self._buildComponent(
            name="model-endpoint-policy",
            status="degraded",
            severity="error",
            detail=(
                f"model endpoint host {modelHost} is not local or private; set "
                "CORTEX_ALLOW_REMOTE_MODEL_ENDPOINT=true only when this is intentional"
            ),
            remediation=(
                "Point CORTEX_OLLAMA_BASE_URL at a local or private endpoint, or set "
                "CORTEX_ALLOW_REMOTE_MODEL_ENDPOINT=true only after explicitly approving "
                "the outbound model dependency."
            ),
        )

    def _checkModelProfile(self) -> RuntimeComponentSchema:
        """Expose the declared generator, embedding, and accelerator profile to operators."""
        return self._buildComponent(
            name="model-profile",
            status="ready",
            severity="info",
            detail=(
                f"generator={self.settings.generatorModel}, "
                f"embedding={self.settings.embeddingModel}, "
                f"requiredAccelerator={self.settings.requiredAccelerator}"
            ),
            remediation=(
                "Keep this profile aligned with the client deployment agreement and the "
                "locally available model artifacts before promoting the package."
            ),
        )

    def _checkPackageBuildProfile(self) -> RuntimeComponentSchema:
        """Expose the packaged Torch wheel channel used for Docling-backed image builds."""
        wheelIndexUrl = self.settings.packagePyTorchWheelIndexUrl
        preinstallPackages = self.settings.packagePyTorchPreinstall
        accelerator = self.settings.requiredAccelerator
        detail = (
            f"torchWheelIndex={wheelIndexUrl}, "
            f"preinstall={preinstallPackages}, "
            f"requiredAccelerator={accelerator}"
        )
        if accelerator == "cpu" and "/cpu" not in wheelIndexUrl:
            return self._buildComponent(
                name="package-build-profile",
                status="degraded",
                severity="error",
                detail=detail,
                remediation=(
                    "Set CORTEX_PACKAGE_PYTORCH_WHEEL_INDEX_URL to the CPU PyTorch wheel "
                    "channel before rebuilding package images for a CPU deployment profile."
                ),
            )
        if accelerator == "cuda" and "/cpu" in wheelIndexUrl:
            return self._buildComponent(
                name="package-build-profile",
                status="degraded",
                severity="error",
                detail=detail,
                remediation=(
                    "Point CORTEX_PACKAGE_PYTORCH_WHEEL_INDEX_URL at the matching CUDA "
                    "PyTorch wheel channel before rebuilding package images for a CUDA deployment."
                ),
            )
        remediation = (
            "Keep this build profile aligned with the package image that was built for the "
            "client deployment target, especially when switching between CPU and CUDA Linux runtimes."
        )
        if accelerator == "mps":
            remediation = (
                "MPS is a local macOS runtime expectation; packaged Linux images should still use "
                "an explicit CPU or CUDA PyTorch wheel channel when they are built."
            )
        return self._buildComponent(
            name="package-build-profile",
            status="ready",
            severity="info",
            detail=detail,
            remediation=remediation,
        )

    def _checkIdentityProfile(self) -> RuntimeComponentSchema:
        """Expose the declared identity mode and OIDC contract to operators."""
        if self.settings.environment == "production" and self.settings.authMode == "fixture":
            return self._buildComponent(
                name="identity-profile",
                status="ready",
                severity="warning",
                detail=(
                    f"authMode={self.settings.authMode}, "
                    f"oidcIssuer={self.settings.oidcIssuerUrl}, "
                    f"oidcAudience={self.settings.oidcAudience}"
                ),
                remediation=(
                    "Fixture auth is suitable for packaged evaluation and local proof flows, "
                    "but client production rollouts should replace it with real bearer tokens "
                    "that match the declared issuer and audience contract."
                ),
            )
        return self._buildComponent(
            name="identity-profile",
            status="ready",
            severity="info",
            detail=(
                f"authMode={self.settings.authMode}, "
                f"oidcIssuer={self.settings.oidcIssuerUrl}, "
                f"oidcAudience={self.settings.oidcAudience}"
            ),
            remediation=(
                "Keep this identity profile aligned with the client authentication boundary "
                "and verify that bearer tokens reaching Cortex match the declared issuer and audience."
            ),
        )

    def _checkAccelerator(self) -> RuntimeComponentSchema:
        actualAccelerator = detectAvailableAccelerator()
        if self.settings.requiredAccelerator not in {"auto", actualAccelerator}:
            return self._buildComponent(
                name="accelerator",
                status="degraded",
                severity="error",
                detail=(
                    f"required {self.settings.requiredAccelerator}, detected {actualAccelerator}"
                ),
                remediation=(
                    "Deploy on hardware that exposes the declared accelerator, or update "
                    "CORTEX_REQUIRED_ACCELERATOR to the runtime that the client profile "
                    "actually intends to support."
                ),
            )
        return self._buildComponent(
            name="accelerator",
            status="ready",
            severity="info",
            detail=f"detected {actualAccelerator}",
        )

    def _checkParserDependencies(self) -> RuntimeComponentSchema:
        """Confirm the local parser toolchain is available for source onboarding."""
        try:
            import docling  # noqa: F401
        except ImportError as error:
            return self._buildComponent(
                name="parser-dependencies",
                status="degraded",
                severity="error",
                detail=f"Docling unavailable: {error}",
                remediation=(
                    "Use the packaged Cortex api/worker images or install the ingestion "
                    "dependencies before enabling source onboarding."
                ),
            )
        return self._buildComponent(
            name="parser-dependencies",
            status="ready",
            severity="info",
            detail="Docling and local parsers available",
        )

    def _checkWebsiteIngestion(self) -> RuntimeComponentSchema:
        """Expose the configured single-page website-ingestion boundary to operators."""
        if not self.settings.websiteAllowlist:
            return self._buildComponent(
                name="website-ingestion",
                status="ready",
                severity="info",
                detail="single-page website ingestion disabled; uploads remain available",
                remediation=(
                    "Set CORTEX_WEBSITE_ALLOWLIST to enable allowlisted website ingestion "
                    "for this client deployment."
                ),
            )
        return self._buildComponent(
            name="website-ingestion",
            status="ready",
            severity="info",
            detail=", ".join(self.settings.websiteAllowlist),
        )

    @staticmethod
    def getFailingComponents(
        runtimeHealth: RuntimeHealthResponse,
    ) -> list[RuntimeComponentSchema]:
        """Return the non-ready runtime components that require operator attention."""
        return [
            component
            for component in runtimeHealth.components
            if component.status != "ready"
        ]

    @staticmethod
    def serializeRuntimeComponents(
        runtimeComponents: list[RuntimeComponentSchema],
    ) -> list[dict[str, str | None]]:
        """Convert runtime-health components into stable structured-log dictionaries."""
        return [
            {
                "name": component.name,
                "status": component.status,
                "severity": component.severity,
                "detail": component.detail,
                "remediation": component.remediation,
            }
            for component in runtimeComponents
        ]

    @staticmethod
    def buildFailureMessage(
        prefix: str,
        failingComponents: list[RuntimeComponentSchema],
    ) -> str:
        """Collapse failing runtime components into one operator-readable startup error."""
        formattedFailures = []
        for component in failingComponents:
            if component.remediation:
                formattedFailures.append(
                    f"{component.name}: {component.detail} | remediation: {component.remediation}"
                )
            else:
                formattedFailures.append(f"{component.name}: {component.detail}")
        return f"{prefix}: " + "; ".join(formattedFailures)

    @staticmethod
    def _buildComponent(
        *,
        name: str,
        status: str,
        severity: str,
        detail: str,
        remediation: str | None = None,
    ) -> RuntimeComponentSchema:
        """Construct one consistent runtime-health component payload."""
        return RuntimeComponentSchema(
            name=name,
            status=status,
            severity=severity,
            detail=detail,
            remediation=remediation,
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

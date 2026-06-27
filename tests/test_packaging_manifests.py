"""Packaging manifest tests keep the shippable split-host deployment examples client-ready."""

from __future__ import annotations

import re
from pathlib import Path


def testKubernetesPackageManifestUsesClientPlaceholdersAndSharedStorage() -> None:
    """The package manifest should model client-owned domains and shared object storage."""
    manifestText = (
        Path(__file__).resolve().parents[1] / "infra" / "k8s" / "cortex-package.yaml"
    ).read_text(encoding="utf-8")
    assert "cortex-console.example.com" in manifestText
    assert "cortex-app.example.com" in manifestText
    assert "cortex-console.hrudainirmal.in" not in manifestText
    assert "cortex-app.hrudainirmal.in" not in manifestText
    assert "kind: ConfigMap" in manifestText
    assert "kind: PersistentVolumeClaim" in manifestText
    assert "claimName: cortex-object-storage" in manifestText
    assert "mountPath: /var/lib/cortex/object-storage" in manifestText
    assert "CORTEX_PACKAGE_PYTORCH_WHEEL_INDEX_URL: https://download.pytorch.org/whl/cpu" in manifestText
    assert 'CORTEX_PACKAGE_PYTORCH_PREINSTALL: "torch torchvision"' in manifestText
    assert "envFrom:" in manifestText
    assert "name: cortex-config" in manifestText


def testKubernetesPackageManifestPreservesSplitHostRouting() -> None:
    """Console and app hosts must both route API paths while keeping separate web surfaces."""
    manifestText = (
        Path(__file__).resolve().parents[1] / "infra" / "k8s" / "cortex-package.yaml"
    ).read_text(encoding="utf-8")
    ingressPathMatches = re.findall(r"(?m)^ {10}- path: (/v1|/health|/)$", manifestText)
    assert ingressPathMatches.count("/v1") == 2
    assert ingressPathMatches.count("/health") == 2
    assert ingressPathMatches.count("/") == 2
    assert "name: cortex-console-web" in manifestText
    assert "name: cortex-query-web" in manifestText
    assert "name: cortex-api" in manifestText


def testKubernetesPackageManifestAddsWorkerStartupChecks() -> None:
    """Worker deployments should expose explicit startup validation to orchestrators."""
    manifestText = (
        Path(__file__).resolve().parents[1] / "infra" / "k8s" / "cortex-package.yaml"
    ).read_text(encoding="utf-8")
    assert 'command: ["python", "-m", "cortex.worker"]' in manifestText
    assert 'command: ["python", "-m", "cortex.worker", "--check-startup"]' in manifestText
    assert "startupProbe:" in manifestText
    assert "livenessProbe:" in manifestText


def testEdgeRouterAdvertisesSplitSurfaceIdentity() -> None:
    """The package router should expose which packaged surface each host resolved to."""
    edgeTemplateText = (
        Path(__file__).resolve().parents[1] / "infra" / "nginx" / "edge.conf.template"
    ).read_text(encoding="utf-8")
    assert "add_header X-Cortex-Surface console always;" in edgeTemplateText
    assert "add_header X-Cortex-Surface query always;" in edgeTemplateText


def testExternalQueryEdgeRouterOmitsBundledQueryUpstream() -> None:
    """The API-only package mode should not require a bundled query-web service."""
    externalEdgeTemplateText = (
        Path(__file__).resolve().parents[1]
        / "infra"
        / "nginx"
        / "edge.external-query.conf.template"
    ).read_text(encoding="utf-8")
    assert "server api:8000;" in externalEdgeTemplateText
    assert "server console-web:8080;" in externalEdgeTemplateText
    assert "server query-web:8080;" not in externalEdgeTemplateText
    assert 'return 404;' in externalEdgeTemplateText


def testDockerComposePackageDefaultsStayOfflineCapable() -> None:
    """Compose defaults should keep Cortex pointed at the local model service by default."""
    composeText = (
        Path(__file__).resolve().parents[1] / "docker-compose.package.yml"
    ).read_text(encoding="utf-8")
    assert composeText.count("CORTEX_ENVIRONMENT: ${CORTEX_ENVIRONMENT:-production}") >= 3
    assert composeText.count("CORTEX_DEV_MODE: ${CORTEX_DEV_MODE:-false}") >= 3
    assert "CORTEX_QUERY_SURFACE_MODE: ${CORTEX_QUERY_SURFACE_MODE:-bundled}" in composeText
    assert "CORTEX_OLLAMA_BASE_URL: ${CORTEX_OLLAMA_BASE_URL:-http://ollama:11434}" in composeText
    assert composeText.count("CORTEX_ALLOW_REMOTE_MODEL_ENDPOINT: ${CORTEX_ALLOW_REMOTE_MODEL_ENDPOINT:-false}") >= 3
    assert composeText.count(
        "CORTEX_PACKAGE_PYTORCH_WHEEL_INDEX_URL: ${CORTEX_PACKAGE_PYTORCH_WHEEL_INDEX_URL:-https://download.pytorch.org/whl/cpu}"
    ) >= 3
    assert composeText.count(
        "CORTEX_PACKAGE_PYTORCH_PREINSTALL: ${CORTEX_PACKAGE_PYTORCH_PREINSTALL:-torch torchvision}"
    ) >= 3
    assert composeText.count("CORTEX_CONSOLE_PUBLIC_URL: ${CORTEX_CONSOLE_PUBLIC_URL:-https://cortex-console.hrudainirmal.in}") >= 4
    assert composeText.count("CORTEX_QUERY_PUBLIC_URL: ${CORTEX_QUERY_PUBLIC_URL:-https://cortex-app.hrudainirmal.in}") >= 4
    assert 'test: ["CMD-SHELL", "python -m cortex.worker --check-startup"]' in composeText


def testExternalQueryComposeOverrideDisablesBundledQueryWeb() -> None:
    """Compose should also ship an API-only package mode for client-owned query shells."""
    composeOverrideText = (
        Path(__file__).resolve().parents[1] / "docker-compose.package.external-query.yml"
    ).read_text(encoding="utf-8")
    assert "query-web:" not in composeOverrideText
    assert "console-web:" in composeOverrideText
    assert "edge:" in composeOverrideText
    assert "CORTEX_QUERY_SURFACE_MODE: ${CORTEX_QUERY_SURFACE_MODE:-external}" in composeOverrideText
    assert "CORTEX_EDGE_TEMPLATE_PATH: /etc/nginx/templates/edge.external-query.conf.template" in composeOverrideText
    assert "query-web:" not in composeOverrideText.split("depends_on:")[-1]


def testPackageDockerfilesPreinstallPyTorchFromAnExplicitWheelChannel() -> None:
    """Package Python images should force the intended torch wheel source before Docling installs."""
    rootDirectory = Path(__file__).resolve().parents[1]
    apiDockerfile = (rootDirectory / "infra" / "docker" / "Dockerfile.api").read_text(
        encoding="utf-8"
    )
    workerDockerfile = (
        rootDirectory / "infra" / "docker" / "Dockerfile.worker"
    ).read_text(encoding="utf-8")
    helperScript = (
        rootDirectory / "infra" / "docker" / "install-python-package.sh"
    ).read_text(encoding="utf-8")
    for dockerfileText in (apiDockerfile, workerDockerfile):
        assert (
            'ARG CORTEX_PACKAGE_PYTORCH_WHEEL_INDEX_URL="https://download.pytorch.org/whl/cpu"'
            in dockerfileText
        )
        assert (
            "COPY infra/docker/install-python-package.sh /usr/local/bin/install-python-package"
            in dockerfileText
        )
        assert "RUN /usr/local/bin/install-python-package '.[dev,ingestion]'" in dockerfileText
    assert 'pip install --no-cache-dir --index-url "$torchWheelIndexUrl" $torchPreinstallPackages' in helperScript
    assert 'pip install --no-cache-dir --extra-index-url "$torchWheelIndexUrl" -e "$projectInstallTarget"' in helperScript


def testFrontendPackageDockerfilesInjectRuntimePublicUrlConfig() -> None:
    """Frontend package images should read client browser hosts at container startup, not build time."""
    rootDirectory = Path(__file__).resolve().parents[1]
    consoleDockerfile = (rootDirectory / "apps" / "web" / "Dockerfile.console").read_text(
        encoding="utf-8"
    )
    queryDockerfile = (rootDirectory / "apps" / "web" / "Dockerfile.query").read_text(
        encoding="utf-8"
    )
    runtimeConfigScript = (
        rootDirectory / "apps" / "web" / "docker-entrypoint.d" / "40-cortex-runtime-config.sh"
    ).read_text(encoding="utf-8")
    publicRuntimeConfig = (
        rootDirectory / "apps" / "web" / "public" / "cortex-runtime-config.js"
    ).read_text(encoding="utf-8")
    for dockerfileText in (consoleDockerfile, queryDockerfile):
        assert "COPY apps/web/docker-entrypoint.d/40-cortex-runtime-config.sh /docker-entrypoint.d/40-cortex-runtime-config.sh" in dockerfileText
        assert "RUN chmod +x /docker-entrypoint.d/40-cortex-runtime-config.sh" in dockerfileText
        assert "ARG VITE_CORTEX_CONSOLE_PUBLIC_URL" not in dockerfileText
        assert "ARG VITE_CORTEX_QUERY_PUBLIC_URL" not in dockerfileText
    assert 'require_env CORTEX_CONSOLE_PUBLIC_URL' in runtimeConfigScript
    assert 'require_env CORTEX_QUERY_PUBLIC_URL' in runtimeConfigScript
    assert 'window.__CORTEX_RUNTIME_CONFIG__ = Object.freeze({' in runtimeConfigScript
    assert "window.__CORTEX_RUNTIME_CONFIG__ = Object.freeze(window.__CORTEX_RUNTIME_CONFIG__ ?? {});" in publicRuntimeConfig


def testFrontendNginxDisablesCachingForRuntimeConfig() -> None:
    """Runtime public-host config should never be cached across client rollouts."""
    nginxConfigText = (
        Path(__file__).resolve().parents[1] / "apps" / "web" / "nginx.static.conf"
    ).read_text(encoding="utf-8")
    assert "location = /cortex-runtime-config.js" in nginxConfigText
    assert 'add_header Cache-Control "no-store, no-cache, must-revalidate" always;' in nginxConfigText
    assert 'add_header Pragma "no-cache" always;' in nginxConfigText
    assert 'add_header Expires "0" always;' in nginxConfigText


def testOpenShiftRoutesPreserveSplitHostsThroughEdgeService() -> None:
    """OpenShift examples should keep the console/query host split intact."""
    routeManifestText = (
        Path(__file__).resolve().parents[1] / "infra" / "openshift" / "cortex-package-routes.yaml"
    ).read_text(encoding="utf-8")
    assert "kind: Route" in routeManifestText
    assert "host: cortex-console.example.com" in routeManifestText
    assert "host: cortex-app.example.com" in routeManifestText
    assert "name: cortex-api" in routeManifestText
    assert "name: cortex-console-web" in routeManifestText
    assert "name: cortex-query-web" in routeManifestText
    routePathMatches = re.findall(r"(?m)^  path: (/.*)$", routeManifestText)
    assert routePathMatches.count("/v1") == 2
    assert routePathMatches.count("/health") == 2
    assert routePathMatches.count("/") == 2


def testEcsTaskFamilyIncludesSplitSurfacesAndSharedObjectStorage() -> None:
    """ECS examples should keep all packaged services and the shared storage mount explicit."""
    taskDefinitionText = (
        Path(__file__).resolve().parents[1] / "infra" / "ecs" / "cortex-task-family.json"
    ).read_text(encoding="utf-8")
    for containerName in ("api", "worker", "console-web", "query-web", "edge"):
        assert f'"name": "{containerName}"' in taskDefinitionText
    assert '"sourceVolume": "cortex-object-storage"' in taskDefinitionText
    assert '"containerPath": "/var/lib/cortex/object-storage"' in taskDefinitionText
    assert '"CORTEX_ENVIRONMENT", "value": "production"' in taskDefinitionText
    assert '"CORTEX_DEV_MODE", "value": "false"' in taskDefinitionText
    assert '"CORTEX_CONSOLE_HOST", "value": "cortex-console.example.com"' in taskDefinitionText
    assert '"CORTEX_QUERY_HOST", "value": "cortex-app.example.com"' in taskDefinitionText
    assert taskDefinitionText.count('"CORTEX_CONSOLE_PUBLIC_URL", "value": "https://cortex-console.example.com"') >= 3
    assert taskDefinitionText.count('"CORTEX_QUERY_PUBLIC_URL", "value": "https://cortex-app.example.com"') >= 3
    assert '"CORTEX_PACKAGE_PYTORCH_WHEEL_INDEX_URL", "value": "https://download.pytorch.org/whl/cpu"' in taskDefinitionText
    assert '"CORTEX_PACKAGE_PYTORCH_PREINSTALL", "value": "torch torchvision"' in taskDefinitionText
    assert '"command": ["CMD-SHELL", "python -m cortex.worker --check-startup"]' in taskDefinitionText


def testEcsMigrationTaskUsesTheSameDeploymentContract() -> None:
    """The ECS migration task should reuse the same split-host and storage contract as runtime tasks."""
    migrationTaskText = (
        Path(__file__).resolve().parents[1] / "infra" / "ecs" / "cortex-migrate-task.json"
    ).read_text(encoding="utf-8")
    assert '"name": "migrate"' in migrationTaskText
    assert '"command": ["alembic", "upgrade", "head"]' in migrationTaskText
    assert '"containerPath": "/var/lib/cortex/object-storage"' in migrationTaskText
    assert '"CORTEX_ENVIRONMENT", "value": "production"' in migrationTaskText
    assert '"CORTEX_DEV_MODE", "value": "false"' in migrationTaskText
    assert '"CORTEX_CONSOLE_HOST", "value": "cortex-console.example.com"' in migrationTaskText
    assert '"CORTEX_QUERY_HOST", "value": "cortex-app.example.com"' in migrationTaskText
    assert '"CORTEX_PACKAGE_PYTORCH_WHEEL_INDEX_URL", "value": "https://download.pytorch.org/whl/cpu"' in migrationTaskText
    assert '"CORTEX_PACKAGE_PYTORCH_PREINSTALL", "value": "torch torchvision"' in migrationTaskText


def testEcsExternalQueryTaskFamilySupportsClientOwnedChatUis() -> None:
    """ECS examples should also ship an API-only package mode for client-owned query shells."""
    taskDefinitionText = (
        Path(__file__).resolve().parents[1]
        / "infra"
        / "ecs"
        / "cortex-task-family-external-query.json"
    ).read_text(encoding="utf-8")
    assert '"name": "api"' in taskDefinitionText
    assert '"name": "worker"' in taskDefinitionText
    assert '"name": "console-web"' in taskDefinitionText
    assert '"name": "query-web"' not in taskDefinitionText
    assert '"name": "edge"' not in taskDefinitionText
    assert '"sourceVolume": "cortex-object-storage"' in taskDefinitionText
    assert '"containerPath": "/var/lib/cortex/object-storage"' in taskDefinitionText
    assert '"CORTEX_ENVIRONMENT", "value": "production"' in taskDefinitionText
    assert '"CORTEX_DEV_MODE", "value": "false"' in taskDefinitionText
    assert '"CORTEX_CONSOLE_PUBLIC_URL", "value": "https://cortex-console.example.com"' in taskDefinitionText
    assert '"CORTEX_QUERY_PUBLIC_URL", "value": "https://cortex-app.example.com"' in taskDefinitionText
    assert '"command": ["CMD-SHELL", "python -m cortex.worker --check-startup"]' in taskDefinitionText


def testKubernetesExternalQueryManifestSupportsClientOwnedChatUis() -> None:
    """Kubernetes examples should also ship an API-only package mode for client-owned query shells."""
    manifestText = (
        Path(__file__).resolve().parents[1]
        / "infra"
        / "k8s"
        / "cortex-package-external-query.yaml"
    ).read_text(encoding="utf-8")
    assert "name: cortex-api" in manifestText
    assert "name: cortex-worker" in manifestText
    assert "name: cortex-console-web" in manifestText
    assert "name: cortex-query-web" not in manifestText
    assert "claimName: cortex-object-storage" in manifestText
    assert "mountPath: /var/lib/cortex/object-storage" in manifestText
    assert "CORTEX_CONSOLE_PUBLIC_URL: https://cortex-console.example.com" in manifestText
    assert "CORTEX_QUERY_PUBLIC_URL: https://cortex-app.example.com" in manifestText
    assert 'command: ["python", "-m", "cortex.worker", "--check-startup"]' in manifestText


def testOpenShiftExternalQueryRoutesSupportClientOwnedChatUis() -> None:
    """OpenShift examples should ship a console-plus-API route set for client-owned query shells."""
    routeManifestText = (
        Path(__file__).resolve().parents[1]
        / "infra"
        / "openshift"
        / "cortex-package-external-query-routes.yaml"
    ).read_text(encoding="utf-8")
    assert "kind: Route" in routeManifestText
    assert "host: cortex-console.example.com" in routeManifestText
    assert "host: cortex-app.example.com" in routeManifestText
    assert "name: cortex-api" in routeManifestText
    assert "name: cortex-console-web" in routeManifestText
    assert "name: cortex-query-web" not in routeManifestText
    routePathMatches = re.findall(r"(?m)^  path: (/.*)$", routeManifestText)
    assert routePathMatches.count("/v1") == 2
    assert routePathMatches.count("/health") == 2
    assert routePathMatches.count("/") == 1

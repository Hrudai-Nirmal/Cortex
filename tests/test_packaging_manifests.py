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


def testEdgeRouterAdvertisesSplitSurfaceIdentity() -> None:
    """The package router should expose which packaged surface each host resolved to."""
    edgeTemplateText = (
        Path(__file__).resolve().parents[1] / "infra" / "nginx" / "edge.conf.template"
    ).read_text(encoding="utf-8")
    assert "add_header X-Cortex-Surface console always;" in edgeTemplateText
    assert "add_header X-Cortex-Surface query always;" in edgeTemplateText


def testDockerComposePackageDefaultsStayOfflineCapable() -> None:
    """Compose defaults should keep Cortex pointed at the local model service by default."""
    composeText = (
        Path(__file__).resolve().parents[1] / "docker-compose.package.yml"
    ).read_text(encoding="utf-8")
    assert "CORTEX_OLLAMA_BASE_URL: ${CORTEX_OLLAMA_BASE_URL:-http://ollama:11434}" in composeText
    assert composeText.count("CORTEX_ALLOW_REMOTE_MODEL_ENDPOINT: ${CORTEX_ALLOW_REMOTE_MODEL_ENDPOINT:-false}") >= 3


def testOpenShiftRoutesPreserveSplitHostsThroughEdgeService() -> None:
    """OpenShift examples should keep the console/query host split intact."""
    routeManifestText = (
        Path(__file__).resolve().parents[1] / "infra" / "openshift" / "cortex-package-routes.yaml"
    ).read_text(encoding="utf-8")
    assert "kind: Route" in routeManifestText
    assert "host: cortex-console.example.com" in routeManifestText
    assert "host: cortex-app.example.com" in routeManifestText
    assert "name: cortex-edge" in routeManifestText


def testEcsTaskFamilyIncludesSplitSurfacesAndSharedObjectStorage() -> None:
    """ECS examples should keep all packaged services and the shared storage mount explicit."""
    taskDefinitionText = (
        Path(__file__).resolve().parents[1] / "infra" / "ecs" / "cortex-task-family.json"
    ).read_text(encoding="utf-8")
    for containerName in ("api", "worker", "console-web", "query-web", "edge"):
        assert f'"name": "{containerName}"' in taskDefinitionText
    assert '"sourceVolume": "cortex-object-storage"' in taskDefinitionText
    assert '"containerPath": "/var/lib/cortex/object-storage"' in taskDefinitionText
    assert '"CORTEX_CONSOLE_HOST", "value": "cortex-console.example.com"' in taskDefinitionText
    assert '"CORTEX_QUERY_HOST", "value": "cortex-app.example.com"' in taskDefinitionText

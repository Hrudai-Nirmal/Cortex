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

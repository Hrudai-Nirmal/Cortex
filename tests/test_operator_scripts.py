"""Operator tooling tests keep the package bootstrap scripts syntactically valid."""

from __future__ import annotations

from pathlib import Path
from subprocess import run


def testPackageScriptsPassBashSyntaxCheck() -> None:
    """Operator scripts should stay parseable before runtime validation begins."""
    rootDirectory = Path(__file__).resolve().parents[1]
    scriptPaths = [
        rootDirectory / "scripts" / "package-up.sh",
        rootDirectory / "scripts" / "package-down.sh",
        rootDirectory / "scripts" / "package-status.sh",
        rootDirectory / "scripts" / "package-logs.sh",
        rootDirectory / "scripts" / "package-pull-models.sh",
        rootDirectory / "scripts" / "package-verify.sh",
    ]
    result = run(
        ["bash", "-n", *[str(scriptPath) for scriptPath in scriptPaths]],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def testPackageEnvExampleDeclaresSplitHostVariables() -> None:
    """The package env example should advertise every deployment-critical host variable."""
    rootDirectory = Path(__file__).resolve().parents[1]
    exampleText = (rootDirectory / ".env.package.example").read_text(encoding="utf-8")
    for requiredName in (
        "CORTEX_ENVIRONMENT",
        "CORTEX_DEV_MODE",
        "CORTEX_CONSOLE_HOST",
        "CORTEX_QUERY_HOST",
        "CORTEX_CONSOLE_PUBLIC_URL",
        "CORTEX_QUERY_PUBLIC_URL",
        "CORTEX_DATABASE_URL",
        "CORTEX_OLLAMA_BASE_URL",
        "CORTEX_GENERATOR_MODEL",
        "CORTEX_EMBEDDING_MODEL",
        "CORTEX_REQUIRED_ACCELERATOR",
        "CORTEX_PACKAGE_PYTORCH_WHEEL_INDEX_URL",
        "CORTEX_PACKAGE_PYTORCH_PREINSTALL",
        "CORTEX_EDGE_PORT",
    ):
        assert f"{requiredName}=" in exampleText


def testPackageEnvExampleDefaultsToOfflineCapableModelPolicy() -> None:
    """The package env example should default to a local model endpoint with remote access off."""
    rootDirectory = Path(__file__).resolve().parents[1]
    exampleText = (rootDirectory / ".env.package.example").read_text(encoding="utf-8")
    assert "CORTEX_ENVIRONMENT=production" in exampleText
    assert "CORTEX_DEV_MODE=false" in exampleText
    assert "CORTEX_OLLAMA_BASE_URL=http://ollama:11434" in exampleText
    assert "CORTEX_ALLOW_REMOTE_MODEL_ENDPOINT=false" in exampleText
    assert "CORTEX_PACKAGE_PYTORCH_WHEEL_INDEX_URL=https://download.pytorch.org/whl/cpu" in exampleText
    assert 'CORTEX_PACKAGE_PYTORCH_PREINSTALL="torch torchvision"' in exampleText


def testPackageVerifyChecksSurfaceAndContractHeaders() -> None:
    """Operator verification should validate split-surface and chat-contract identity headers."""
    rootDirectory = Path(__file__).resolve().parents[1]
    verifyText = (rootDirectory / "scripts" / "package-verify.sh").read_text(encoding="utf-8")
    assert "X-Cortex-Surface: console" in verifyText
    assert "X-Cortex-Surface: query" in verifyText
    assert 'read_json "$CORTEX_QUERY_HOST" "/health/live"' in verifyText
    assert 'read_json "$CORTEX_QUERY_HOST" "/health/startup"' in verifyText
    assert 'read_json "$CORTEX_QUERY_HOST" "/health/ready"' in verifyText
    assert "X-Cortex-Contract-Version: v1" in verifyText
    assert '"contractVersion":"v1"' in verifyText
    assert '"traceEventsPath"' in verifyText


def testPackageUpPrintsStructuredStartupFailures() -> None:
    """Package bootstrap should surface failing health components instead of a generic timeout."""
    rootDirectory = Path(__file__).resolve().parents[1]
    scriptText = (rootDirectory / "scripts" / "package-up.sh").read_text(encoding="utf-8")
    assert 'require_env CORTEX_ENVIRONMENT' in scriptText
    assert 'require_env CORTEX_DEV_MODE' in scriptText
    assert 'require_one_of "$CORTEX_ENVIRONMENT" "CORTEX_ENVIRONMENT" production' in scriptText
    assert 'require_one_of "$CORTEX_DEV_MODE" "CORTEX_DEV_MODE" false' in scriptText
    assert 'require_env CORTEX_GENERATOR_MODEL' in scriptText
    assert 'require_env CORTEX_EMBEDDING_MODEL' in scriptText
    assert 'require_env CORTEX_REQUIRED_ACCELERATOR' in scriptText
    assert 'require_env CORTEX_PACKAGE_PYTORCH_WHEEL_INDEX_URL' in scriptText
    assert 'require_one_of "$CORTEX_REQUIRED_ACCELERATOR" "CORTEX_REQUIRED_ACCELERATOR" cpu mps cuda' in scriptText
    assert 'validate_torch_build_profile "$CORTEX_REQUIRED_ACCELERATOR" "$CORTEX_PACKAGE_PYTORCH_WHEEL_INDEX_URL"' in scriptText
    assert 'wait_for_health_ready "$CORTEX_CONSOLE_HOST" "/health/startup" "startup validation"' in scriptText
    assert 'wait_for_health_ready "$CORTEX_QUERY_HOST" "/health/startup" "query-host startup validation"' in scriptText
    assert 'wait_for_endpoint "$CORTEX_CONSOLE_HOST" "/" "<!doctype html" 40' in scriptText
    assert 'assert_surface_header "$CORTEX_CONSOLE_HOST" "console"' in scriptText
    assert 'assert_surface_header "$CORTEX_QUERY_HOST" "query"' in scriptText
    assert 'wait_for_health_ready "$CORTEX_CONSOLE_HOST" "/health/ready" "runtime readiness"' in scriptText
    assert 'wait_for_health_ready "$CORTEX_QUERY_HOST" "/health/ready" "query-host runtime readiness"' in scriptText
    assert 'echo "Package ${label} failed."' in scriptText
    assert 'print_health_failures "$payload"' in scriptText
    assert 'echo "Package PyTorch wheel source: ${CORTEX_PACKAGE_PYTORCH_WHEEL_INDEX_URL}"' in scriptText


def testPackageStatusReportsBothHostsAndSurfaceIdentity() -> None:
    """Package status should show routed surface identity and both host health views."""
    rootDirectory = Path(__file__).resolve().parents[1]
    scriptText = (rootDirectory / "scripts" / "package-status.sh").read_text(encoding="utf-8")
    assert 'read_json "$CORTEX_QUERY_HOST" "/health/startup"' in scriptText
    assert 'read_json "$CORTEX_QUERY_HOST" "/health/ready"' in scriptText
    assert 'read_headers "$CORTEX_CONSOLE_HOST" "/"' in scriptText
    assert 'read_headers "$CORTEX_QUERY_HOST" "/"' in scriptText
    assert 'echo "Surface routing:"' in scriptText
    assert 'print_surface_identity "$CORTEX_CONSOLE_HOST" "$console_headers"' in scriptText
    assert 'print_surface_identity "$CORTEX_QUERY_HOST" "$query_headers"' in scriptText

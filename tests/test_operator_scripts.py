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
        "CORTEX_CONSOLE_HOST",
        "CORTEX_QUERY_HOST",
        "CORTEX_CONSOLE_PUBLIC_URL",
        "CORTEX_QUERY_PUBLIC_URL",
        "CORTEX_DATABASE_URL",
        "CORTEX_OLLAMA_BASE_URL",
        "CORTEX_GENERATOR_MODEL",
        "CORTEX_EMBEDDING_MODEL",
        "CORTEX_EDGE_PORT",
    ):
        assert f"{requiredName}=" in exampleText


def testPackageEnvExampleDefaultsToOfflineCapableModelPolicy() -> None:
    """The package env example should default to a local model endpoint with remote access off."""
    rootDirectory = Path(__file__).resolve().parents[1]
    exampleText = (rootDirectory / ".env.package.example").read_text(encoding="utf-8")
    assert "CORTEX_OLLAMA_BASE_URL=http://ollama:11434" in exampleText
    assert "CORTEX_ALLOW_REMOTE_MODEL_ENDPOINT=false" in exampleText


def testPackageVerifyChecksSurfaceAndContractHeaders() -> None:
    """Operator verification should validate split-surface and chat-contract identity headers."""
    rootDirectory = Path(__file__).resolve().parents[1]
    verifyText = (rootDirectory / "scripts" / "package-verify.sh").read_text(encoding="utf-8")
    assert "X-Cortex-Surface: console" in verifyText
    assert "X-Cortex-Surface: query" in verifyText
    assert "X-Cortex-Contract-Version: v1" in verifyText
    assert '"contractVersion":"v1"' in verifyText
    assert '"traceEventsPath"' in verifyText


def testPackageUpPrintsStructuredStartupFailures() -> None:
    """Package bootstrap should surface failing health components instead of a generic timeout."""
    rootDirectory = Path(__file__).resolve().parents[1]
    scriptText = (rootDirectory / "scripts" / "package-up.sh").read_text(encoding="utf-8")
    assert 'wait_for_health_ready "$CORTEX_CONSOLE_HOST" "/health/startup" "startup validation"' in scriptText
    assert 'wait_for_health_ready "$CORTEX_CONSOLE_HOST" "/health/ready" "runtime readiness"' in scriptText
    assert 'echo "Package ${label} failed."' in scriptText
    assert 'print_health_failures "$payload"' in scriptText

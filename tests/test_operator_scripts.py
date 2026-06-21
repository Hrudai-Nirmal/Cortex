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

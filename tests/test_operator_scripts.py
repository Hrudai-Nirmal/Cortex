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
        "CORTEX_QUERY_SURFACE_MODE",
        "CORTEX_AUTH_MODE",
        "CORTEX_CONSOLE_HOST",
        "CORTEX_QUERY_HOST",
        "CORTEX_CONSOLE_PUBLIC_URL",
        "CORTEX_QUERY_PUBLIC_URL",
        "CORTEX_DATABASE_URL",
        "CORTEX_OLLAMA_BASE_URL",
        "CORTEX_ALLOW_REMOTE_MODEL_ENDPOINT",
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
    """Operator verification should validate split-surface, runtime-config, and rich contract semantics."""
    rootDirectory = Path(__file__).resolve().parents[1]
    verifyText = (rootDirectory / "scripts" / "package-verify.sh").read_text(encoding="utf-8")
    assert 'require_docker_daemon' in verifyText
    assert 'docker info >/dev/null 2>&1' in verifyText
    assert "Docker is installed but the daemon is not reachable." in verifyText
    assert 'assert_contains() {' in verifyText
    assert 'Package verification failed: expected ${description}.' in verifyText
    assert "X-Cortex-Surface: console" in verifyText
    assert "X-Cortex-Surface: query" in verifyText
    assert 'read_json "$CORTEX_QUERY_HOST" "/health/live"' in verifyText
    assert 'read_json "$CORTEX_QUERY_HOST" "/health/startup"' in verifyText
    assert 'read_json "$CORTEX_QUERY_HOST" "/health/ready"' in verifyText
    assert "X-Cortex-Contract-Version: v1" in verifyText
    assert 'read_json "$CORTEX_QUERY_HOST" "/v1/chat/contracts/v1"' in verifyText
    assert 'read_text "$CORTEX_CONSOLE_HOST" "/cortex-runtime-config.js"' in verifyText
    assert 'read_text "$CORTEX_QUERY_HOST" "/cortex-runtime-config.js"' in verifyText
    assert 'read_headers "$CORTEX_CONSOLE_HOST" "/cortex-runtime-config.js"' in verifyText
    assert 'read_headers "$CORTEX_QUERY_HOST" "/cortex-runtime-config.js"' in verifyText
    assert 'assert_contains "$console_runtime_config_headers" "Cache-Control: no-store, no-cache, must-revalidate" "console runtime-config cache policy"' in verifyText
    assert 'assert_contains "$query_runtime_config_headers" "Cache-Control: no-store, no-cache, must-revalidate" "query runtime-config cache policy"' in verifyText
    assert 'consolePublicUrl: \\"${CORTEX_CONSOLE_PUBLIC_URL}\\"' in verifyText
    assert 'queryPublicUrl: \\"${CORTEX_QUERY_PUBLIC_URL}\\"' in verifyText
    assert '"contractVersion":"v1"' in verifyText
    assert '"endpointPath":"/v1/chat/completions"' in verifyText
    assert '"authentication":"bearer-token"' in verifyText
    assert '"requestOptions"' in verifyText
    assert '"querySurfaceMode"' in verifyText
    assert '"bundledQueryUiAvailable"' in verifyText
    assert "console_startup=" in verifyText
    assert "query_startup=" in verifyText
    assert '"startupPolicy":"fail-closed"' not in verifyText
    assert 'assert_contains "$console_startup" "startupPolicy=fail-closed"' in verifyText
    assert 'assert_contains "$query_startup" "startupPolicy=fail-closed"' in verifyText
    assert 'assert_contains "$console_startup" "console=${CORTEX_CONSOLE_PUBLIC_URL}"' in verifyText
    assert 'assert_contains "$console_startup" "query=${CORTEX_QUERY_PUBLIC_URL}"' in verifyText
    assert 'assert_contains "$query_startup" "console=${CORTEX_CONSOLE_PUBLIC_URL}"' in verifyText
    assert 'assert_contains "$query_startup" "query=${CORTEX_QUERY_PUBLIC_URL}"' in verifyText
    assert 'assert_contains "$console_startup" "querySurfaceMode=${CORTEX_QUERY_SURFACE_MODE}"' in verifyText
    assert 'assert_contains "$query_startup" "querySurfaceMode=${CORTEX_QUERY_SURFACE_MODE}"' in verifyText
    assert '"userMessageSelectionPolicy":"last-non-empty-user-message"' in verifyText
    assert '"streamRequiredValue":false' in verifyText
    assert '"supportsCitationToggle":true' in verifyText
    assert '"employeeSafeExtensionFields"' in verifyText
    assert '"operatorOnlyExtensionFields"' in verifyText
    assert '"errorStatuses"' in verifyText
    assert '"evidenceStatuses"' in verifyText
    assert '"routes"' in verifyText
    assert '"abstentionEvidenceStatuses"' in verifyText
    assert '"code":"invalid_request"' in verifyText
    assert '"code":"forbidden_scope"' in verifyText
    assert '"code":"provider_unavailable"' in verifyText
    assert '"code":"internal_error"' in verifyText
    assert '"sufficient"' in verifyText
    assert '"partial"' in verifyText
    assert '"insufficient"' in verifyText
    assert '"conflict"' in verifyText
    assert '"retrieve-then-compute"' in verifyText
    assert '"traceEventsPath"' in verifyText
    assert 'assert_contains "$console_headers" "X-Cortex-Surface: console" "console surface header"' in verifyText
    assert 'assert_contains "$query_headers" "X-Cortex-Surface: query" "query surface header"' in verifyText
    assert 'assert_contains "$query_contract" \'"contractVersion":"v1"\' "query contract version"' in verifyText
    assert 'assert_contains "$chat_response" \'"x_cortex"\' "chat response extension payload"' in verifyText
    assert 'assert_worker_startup_check() {' in verifyText
    assert 'Package verification failed: worker startup check is blocked.' in verifyText
    assert 'echo "Run pnpm package:status for the current routed health and contract summary."' in verifyText
    assert 'docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" exec -T worker \\' in verifyText
    assert 'python -m cortex.worker --check-startup >/dev/null 2>&1' in verifyText


def testPackageUpPrintsStructuredStartupFailures() -> None:
    """Package bootstrap should surface failing health components instead of a generic timeout."""
    rootDirectory = Path(__file__).resolve().parents[1]
    scriptText = (rootDirectory / "scripts" / "package-up.sh").read_text(encoding="utf-8")
    assert 'require_docker_daemon' in scriptText
    assert 'docker info >/dev/null 2>&1' in scriptText
    assert "Start Docker Desktop or the target container runtime before running package commands." in scriptText
    assert 'require_env CORTEX_ENVIRONMENT' in scriptText
    assert 'require_env CORTEX_DEV_MODE' in scriptText
    assert 'require_env CORTEX_QUERY_SURFACE_MODE' in scriptText
    assert 'require_env CORTEX_AUTH_MODE' in scriptText
    assert 'require_one_of "$CORTEX_ENVIRONMENT" "CORTEX_ENVIRONMENT" production' in scriptText
    assert 'require_one_of "$CORTEX_DEV_MODE" "CORTEX_DEV_MODE" false' in scriptText
    assert 'require_one_of "$CORTEX_QUERY_SURFACE_MODE" "CORTEX_QUERY_SURFACE_MODE" bundled external' in scriptText
    assert 'require_env CORTEX_ALLOW_REMOTE_MODEL_ENDPOINT' in scriptText
    assert 'require_one_of "$CORTEX_ALLOW_REMOTE_MODEL_ENDPOINT" "CORTEX_ALLOW_REMOTE_MODEL_ENDPOINT" true false' in scriptText
    assert 'require_env CORTEX_GENERATOR_MODEL' in scriptText
    assert 'require_env CORTEX_EMBEDDING_MODEL' in scriptText
    assert 'require_env CORTEX_REQUIRED_ACCELERATOR' in scriptText
    assert 'require_env CORTEX_PACKAGE_PYTORCH_WHEEL_INDEX_URL' in scriptText
    assert 'require_one_of "$CORTEX_REQUIRED_ACCELERATOR" "CORTEX_REQUIRED_ACCELERATOR" cpu mps cuda' in scriptText
    assert 'validate_torch_build_profile "$CORTEX_REQUIRED_ACCELERATOR" "$CORTEX_PACKAGE_PYTORCH_WHEEL_INDEX_URL"' in scriptText
    assert 'require_numeric_port "$CORTEX_EDGE_PORT" "CORTEX_EDGE_PORT"' in scriptText
    assert 'require_absolute_path "$CORTEX_OBJECT_STORAGE_ROOT" "CORTEX_OBJECT_STORAGE_ROOT"' in scriptText
    assert 'require_https_public_url "$CORTEX_CONSOLE_PUBLIC_URL" "CORTEX_CONSOLE_PUBLIC_URL"' in scriptText
    assert 'require_https_public_url "$CORTEX_QUERY_PUBLIC_URL" "CORTEX_QUERY_PUBLIC_URL"' in scriptText
    assert 'validate_model_endpoint_policy "$CORTEX_OLLAMA_BASE_URL" "$CORTEX_ALLOW_REMOTE_MODEL_ENDPOINT"' in scriptText
    assert 'is_reserved_placeholder_host' in scriptText
    assert "must be replaced with the client's real domains" in scriptText
    assert 'wait_for_health_ready "$CORTEX_CONSOLE_HOST" "/health/startup" "startup validation"' in scriptText
    assert 'wait_for_endpoint "$CORTEX_CONSOLE_HOST" "/" "<!doctype html" 40' in scriptText
    assert 'assert_surface_header "$CORTEX_CONSOLE_HOST" "console"' in scriptText
    assert 'assert_runtime_config "$CORTEX_CONSOLE_HOST" "$CORTEX_CONSOLE_PUBLIC_URL" "$CORTEX_QUERY_PUBLIC_URL"' in scriptText
    assert 'assert_runtime_config_cache_header "$CORTEX_CONSOLE_HOST"' in scriptText
    assert 'wait_for_health_ready "$CORTEX_CONSOLE_HOST" "/health/ready" "runtime readiness"' in scriptText
    assert 'if [ "$CORTEX_QUERY_SURFACE_MODE" = "bundled" ]; then' in scriptText
    assert 'wait_for_health_ready "$CORTEX_QUERY_HOST" "/health/startup" "query-host startup validation"' in scriptText
    assert 'assert_surface_header "$CORTEX_QUERY_HOST" "query"' in scriptText
    assert 'assert_runtime_config "$CORTEX_QUERY_HOST" "$CORTEX_CONSOLE_PUBLIC_URL" "$CORTEX_QUERY_PUBLIC_URL"' in scriptText
    assert 'assert_runtime_config_cache_header "$CORTEX_QUERY_HOST"' in scriptText
    assert 'wait_for_health_ready "$CORTEX_QUERY_HOST" "/health/ready" "query-host runtime readiness"' in scriptText
    assert 'else' in scriptText
    assert 'wait_for_health_ready "$CORTEX_QUERY_HOST" "/health/startup" "query-host api startup validation"' in scriptText
    assert 'wait_for_health_ready "$CORTEX_QUERY_HOST" "/health/ready" "query-host api runtime readiness"' in scriptText
    assert 'echo "Query surface mode: ${CORTEX_QUERY_SURFACE_MODE}"' in scriptText
    assert 'wait_for_worker_startup_check' in scriptText
    assert 'python -m cortex.worker --check-startup >/dev/null 2>&1' in scriptText
    assert 'echo "Package ${label} failed."' in scriptText
    assert 'print_health_failures "$payload"' in scriptText
    assert 'print_compose_diagnostics' in scriptText
    assert 'docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" ps' in scriptText
    assert 'docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" logs --tail=40 api worker edge' in scriptText
    assert 'echo "Package PyTorch wheel source: ${CORTEX_PACKAGE_PYTORCH_WHEEL_INDEX_URL}"' in scriptText


def testPackageStatusReportsBothHostsAndSurfaceIdentity() -> None:
    """Package status should show routed surface identity plus the rich replacement-UI contract."""
    rootDirectory = Path(__file__).resolve().parents[1]
    scriptText = (rootDirectory / "scripts" / "package-status.sh").read_text(encoding="utf-8")
    assert 'require_docker_daemon' in scriptText
    assert 'docker info >/dev/null 2>&1' in scriptText
    assert 'read_json "$CORTEX_QUERY_HOST" "/health/startup"' in scriptText
    assert 'read_json "$CORTEX_QUERY_HOST" "/health/ready"' in scriptText
    assert 'read_json "$CORTEX_QUERY_HOST" "/v1/chat/contracts/v1"' in scriptText
    assert 'read_text "$CORTEX_CONSOLE_HOST" "/cortex-runtime-config.js"' in scriptText
    assert 'read_headers "$CORTEX_CONSOLE_HOST" "/cortex-runtime-config.js"' in scriptText
    assert 'read_headers "$CORTEX_CONSOLE_HOST" "/"' in scriptText
    assert 'echo "Surface routing:"' in scriptText
    assert 'print_surface_identity "$CORTEX_CONSOLE_HOST" "$console_headers"' in scriptText
    assert 'print_deployment_contract_summary "$startup_payload"' in scriptText
    assert "deployment contract:" in scriptText
    assert "startupPolicy=" in scriptText
    assert "querySurfaceMode=" in scriptText
    assert 'print_runtime_config_summary "console" "$console_runtime_config"' in scriptText
    assert 'print_cache_header_summary "console" "$console_runtime_config_headers"' in scriptText
    assert 'try_read_json "$CORTEX_QUERY_HOST" "/v1/chat/contracts/v1"' in scriptText
    assert 'query contract: unavailable' in scriptText
    assert "query contract detail:" in scriptText
    assert 'print_contract_summary "$query_contract_payload"' in scriptText
    assert 'echo "Query surface mode: ${CORTEX_QUERY_SURFACE_MODE}"' in scriptText
    assert 'if [ "$CORTEX_QUERY_SURFACE_MODE" = "bundled" ]; then' in scriptText
    assert 'read_text "$CORTEX_QUERY_HOST" "/cortex-runtime-config.js"' in scriptText
    assert 'read_headers "$CORTEX_QUERY_HOST" "/cortex-runtime-config.js"' in scriptText
    assert 'read_headers "$CORTEX_QUERY_HOST" "/"' in scriptText
    assert 'print_surface_identity "$CORTEX_QUERY_HOST" "$query_headers"' in scriptText
    assert 'print_runtime_config_summary "query" "$query_runtime_config"' in scriptText
    assert 'print_cache_header_summary "query" "$query_runtime_config_headers"' in scriptText
    assert 'echo "  ${CORTEX_QUERY_HOST} -> external-query-ui (not bundled)"' in scriptText
    assert 'request semantics' in scriptText
    assert 'employee-safe fields' in scriptText
    assert 'operator-only fields' in scriptText
    assert 'error statuses' in scriptText
    assert 'print_worker_status' in scriptText
    assert 'python -m cortex.worker --check-startup >/dev/null 2>&1' in scriptText
    assert 'echo "worker startup: ready"' in scriptText


def testSupportingPackageScriptsAlsoCheckDockerDaemon() -> None:
    """Every package helper script should fail fast when the Docker daemon is unavailable."""
    rootDirectory = Path(__file__).resolve().parents[1]
    for scriptName in ("package-down.sh", "package-logs.sh", "package-pull-models.sh"):
        scriptText = (rootDirectory / "scripts" / scriptName).read_text(encoding="utf-8")
        assert 'require_docker_daemon' in scriptText
        assert 'docker info >/dev/null 2>&1' in scriptText
        assert "Docker is installed but the daemon is not reachable." in scriptText


def testPackagePullModelsRejectsRemoteModelProfiles() -> None:
    """Model pull helper should fail fast when Cortex is configured to use a remote endpoint."""
    rootDirectory = Path(__file__).resolve().parents[1]
    scriptText = (rootDirectory / "scripts" / "package-pull-models.sh").read_text(
        encoding="utf-8"
    )
    assert 'require_env CORTEX_ALLOW_REMOTE_MODEL_ENDPOINT' in scriptText
    assert 'require_env CORTEX_OLLAMA_BASE_URL' in scriptText
    assert 'if [ "$CORTEX_ALLOW_REMOTE_MODEL_ENDPOINT" = "true" ]; then' in scriptText
    assert "package:pull-models only manages the bundled local Ollama service." in scriptText
    assert "Disable CORTEX_ALLOW_REMOTE_MODEL_ENDPOINT or pull the required models into the remote provider directly." in scriptText


def testPackageVerifySupportsExternalQueryUiMode() -> None:
    """Package verification should keep the query API contract checks even when query-web is not bundled."""
    rootDirectory = Path(__file__).resolve().parents[1]
    verifyText = (rootDirectory / "scripts" / "package-verify.sh").read_text(encoding="utf-8")
    assert 'require_env CORTEX_QUERY_SURFACE_MODE' in verifyText
    assert 'if [ "$CORTEX_QUERY_SURFACE_MODE" = "bundled" ]; then' in verifyText
    assert 'assert_contains "$query_html" "<!doctype html" "query HTML shell"' in verifyText
    assert 'assert_contains "$query_headers" "X-Cortex-Surface: query" "query surface header"' in verifyText
    assert 'assert_contains "$query_runtime_config_headers" "Cache-Control: no-store, no-cache, must-revalidate" "query runtime-config cache policy"' in verifyText
    assert 'assert_contains "$query_runtime_config" "consolePublicUrl: \\"${CORTEX_CONSOLE_PUBLIC_URL}\\"" "query runtime-config consolePublicUrl"' in verifyText
    assert 'assert_contains "$query_runtime_config" "queryPublicUrl: \\"${CORTEX_QUERY_PUBLIC_URL}\\"" "query runtime-config queryPublicUrl"' in verifyText
    assert 'else' in verifyText
    assert 'echo "Package verification: query host is running in external-query mode; skipping bundled query-web shell checks."' in verifyText
    assert 'assert_contains "$(read_json "$CORTEX_QUERY_HOST" "/health/live")" \'"status"\' "query live health payload"' in verifyText
    assert 'query_contract="$(read_json "$CORTEX_QUERY_HOST" "/v1/chat/contracts/v1")"' in verifyText

#!/usr/bin/env bash
# Verify split-host routing, health probes, and the external query contract on a running package.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="${1:-$ROOT_DIR/.env.package}"
DEFAULT_COMPOSE_FILE="$ROOT_DIR/docker-compose.package.yml"
EXTERNAL_QUERY_COMPOSE_FILE="$ROOT_DIR/docker-compose.package.external-query.yml"
COMPOSE_FILE="$DEFAULT_COMPOSE_FILE"

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}

require_docker_daemon() {
  if docker info >/dev/null 2>&1; then
    return 0
  fi
  echo "Docker is installed but the daemon is not reachable." >&2
  echo "Start Docker Desktop or the target container runtime before running package commands." >&2
  exit 1
}

assert_contains() {
  local haystack="$1"
  local needle="$2"
  local description="$3"

  if printf "%s" "$haystack" | grep -Fiq "$needle"; then
    return 0
  fi

  echo "Package verification failed: expected ${description}." >&2
  echo "Missing text: ${needle}" >&2
  echo "Run pnpm package:status for the current routed health and contract summary." >&2
  exit 1
}

assert_worker_startup_check() {
  if docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" exec -T worker \
    python -m cortex.worker --check-startup >/dev/null 2>&1; then
    return 0
  fi

  echo "Package verification failed: worker startup check is blocked." >&2
  echo "Run pnpm package:status for the current routed health and contract summary." >&2
  exit 1
}

read_json() {
  local host="$1"
  local path="$2"
  curl --silent --show-error --fail -H "Host: ${host}" "http://127.0.0.1:${CORTEX_EDGE_PORT}${path}"
}

read_text() {
  local host="$1"
  local path="$2"
  curl --silent --show-error --fail -H "Host: ${host}" "http://127.0.0.1:${CORTEX_EDGE_PORT}${path}"
}

read_headers() {
  local host="$1"
  local path="$2"
  curl --silent --show-error --fail -D - -o /dev/null -H "Host: ${host}" "http://127.0.0.1:${CORTEX_EDGE_PORT}${path}" | tr -d '\r'
}

require_command curl
require_command docker
require_docker_daemon

if [ ! -f "$ENV_FILE" ]; then
  echo "Package env file not found: $ENV_FILE" >&2
  exit 1
fi

set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a

require_env() {
  local name="$1"
  if [ -z "${!name:-}" ]; then
    echo "Missing required environment value: $name" >&2
    exit 1
  fi
}

require_env CORTEX_QUERY_SURFACE_MODE

if [ "$CORTEX_QUERY_SURFACE_MODE" = "external" ]; then
  COMPOSE_FILE="$EXTERNAL_QUERY_COMPOSE_FILE"
fi

console_html="$(curl --silent --show-error --fail -H "Host: ${CORTEX_CONSOLE_HOST}" "http://127.0.0.1:${CORTEX_EDGE_PORT}/")"
console_headers="$(curl --silent --show-error --fail -D - -o /dev/null -H "Host: ${CORTEX_CONSOLE_HOST}" "http://127.0.0.1:${CORTEX_EDGE_PORT}/" | tr -d '\r')"
console_runtime_config_headers="$(read_headers "$CORTEX_CONSOLE_HOST" "/cortex-runtime-config.js")"

assert_contains "$console_html" "<!doctype html" "console HTML shell"
assert_contains "$console_headers" "X-Cortex-Surface: console" "console surface header"
assert_contains "$console_runtime_config_headers" "Cache-Control: no-store, no-cache, must-revalidate" "console runtime-config cache policy"
console_runtime_config="$(read_text "$CORTEX_CONSOLE_HOST" "/cortex-runtime-config.js")"
assert_contains "$console_runtime_config" "consolePublicUrl: \"${CORTEX_CONSOLE_PUBLIC_URL}\"" "console runtime-config consolePublicUrl"
assert_contains "$console_runtime_config" "queryPublicUrl: \"${CORTEX_QUERY_PUBLIC_URL}\"" "console runtime-config queryPublicUrl"

if [ "$CORTEX_QUERY_SURFACE_MODE" = "bundled" ]; then
  query_html="$(curl --silent --show-error --fail -H "Host: ${CORTEX_QUERY_HOST}" "http://127.0.0.1:${CORTEX_EDGE_PORT}/")"
  query_headers="$(curl --silent --show-error --fail -D - -o /dev/null -H "Host: ${CORTEX_QUERY_HOST}" "http://127.0.0.1:${CORTEX_EDGE_PORT}/" | tr -d '\r')"
  query_runtime_config_headers="$(read_headers "$CORTEX_QUERY_HOST" "/cortex-runtime-config.js")"
  query_runtime_config="$(read_text "$CORTEX_QUERY_HOST" "/cortex-runtime-config.js")"
  assert_contains "$query_html" "<!doctype html" "query HTML shell"
  assert_contains "$query_headers" "X-Cortex-Surface: query" "query surface header"
  assert_contains "$query_runtime_config_headers" "Cache-Control: no-store, no-cache, must-revalidate" "query runtime-config cache policy"
  assert_contains "$query_runtime_config" "consolePublicUrl: \"${CORTEX_CONSOLE_PUBLIC_URL}\"" "query runtime-config consolePublicUrl"
  assert_contains "$query_runtime_config" "queryPublicUrl: \"${CORTEX_QUERY_PUBLIC_URL}\"" "query runtime-config queryPublicUrl"
else
  echo "Package verification: query host is running in external-query mode; skipping bundled query-web shell checks."
fi

assert_contains "$(read_json "$CORTEX_CONSOLE_HOST" "/health/live")" '"status"' "console live health payload"
assert_contains "$(read_json "$CORTEX_QUERY_HOST" "/health/live")" '"status"' "query live health payload"
console_startup="$(read_json "$CORTEX_CONSOLE_HOST" "/health/startup")"
query_startup="$(read_json "$CORTEX_QUERY_HOST" "/health/startup")"
console_ready="$(read_json "$CORTEX_CONSOLE_HOST" "/health/ready")"
query_ready="$(read_json "$CORTEX_QUERY_HOST" "/health/ready")"
assert_contains "$console_startup" '"components"' "console startup health payload"
assert_contains "$query_startup" '"components"' "query startup health payload"
assert_contains "$console_startup" "startupPolicy=fail-closed" "console startup policy"
assert_contains "$query_startup" "startupPolicy=fail-closed" "query startup policy"
assert_contains "$console_startup" "console=${CORTEX_CONSOLE_PUBLIC_URL}" "console startup public console URL"
assert_contains "$console_startup" "query=${CORTEX_QUERY_PUBLIC_URL}" "console startup public query URL"
assert_contains "$query_startup" "console=${CORTEX_CONSOLE_PUBLIC_URL}" "query startup public console URL"
assert_contains "$query_startup" "query=${CORTEX_QUERY_PUBLIC_URL}" "query startup public query URL"
assert_contains "$console_startup" "querySurfaceMode=${CORTEX_QUERY_SURFACE_MODE}" "console startup query-surface mode"
assert_contains "$query_startup" "querySurfaceMode=${CORTEX_QUERY_SURFACE_MODE}" "query startup query-surface mode"
assert_contains "$console_ready" '"status":"ready"' "console ready health status"
assert_contains "$query_ready" '"status":"ready"' "query ready health status"
query_contract="$(read_json "$CORTEX_QUERY_HOST" "/v1/chat/contracts/v1")"
assert_contains "$query_contract" '"contractVersion":"v1"' "query contract version"
assert_contains "$query_contract" '"endpointPath":"/v1/chat/completions"' "query contract endpoint path"
assert_contains "$query_contract" '"authentication":"bearer-token"' "query contract authentication mode"
assert_contains "$query_contract" '"requestOptions"' "query contract request options"
assert_contains "$query_contract" '"querySurfaceMode":"' "query contract surface mode"
assert_contains "$query_contract" '"bundledQueryUiAvailable":' "query contract bundled query-ui availability"
assert_contains "$query_contract" '"userMessageSelectionPolicy":"last-non-empty-user-message"' "query contract user-message selection policy"
assert_contains "$query_contract" '"streamRequiredValue":false' "query contract stream requirement"
assert_contains "$query_contract" '"supportsCitationToggle":true' "query contract citation toggle support"
assert_contains "$query_contract" '"traceEventsPathTemplate":"/v1/query/{traceId}/events"' "query contract trace-events template"
assert_contains "$query_contract" '"responseHeaders"' "query contract response headers"
assert_contains "$query_contract" '"extensionFields"' "query contract extension fields"
assert_contains "$query_contract" '"employeeSafeExtensionFields"' "query contract employee-safe fields"
assert_contains "$query_contract" '"operatorOnlyExtensionFields"' "query contract operator-only fields"
assert_contains "$query_contract" '"errorStatuses"' "query contract error statuses"
assert_contains "$query_contract" '"evidenceStatuses"' "query contract evidence statuses"
assert_contains "$query_contract" '"routes"' "query contract routes"
assert_contains "$query_contract" '"abstentionEvidenceStatuses"' "query contract abstention evidence statuses"
assert_contains "$query_contract" '"code":"invalid_request"' "query contract invalid_request code"
assert_contains "$query_contract" '"code":"forbidden_scope"' "query contract forbidden_scope code"
assert_contains "$query_contract" '"code":"provider_unavailable"' "query contract provider_unavailable code"
assert_contains "$query_contract" '"code":"internal_error"' "query contract internal_error code"
assert_contains "$query_contract" '"sufficient"' "query contract sufficient evidence status"
assert_contains "$query_contract" '"partial"' "query contract partial evidence status"
assert_contains "$query_contract" '"insufficient"' "query contract insufficient evidence status"
assert_contains "$query_contract" '"conflict"' "query contract conflict evidence status"
assert_contains "$query_contract" '"retrieve-then-compute"' "query contract retrieve-then-compute route"
if [ "$CORTEX_QUERY_SURFACE_MODE" = "bundled" ]; then
  assert_contains "$query_contract" '"querySurfaceMode":"bundled"' "bundled query-surface mode"
  assert_contains "$query_contract" '"bundledQueryUiAvailable":true' "bundled query-ui availability"
else
  assert_contains "$query_contract" '"querySurfaceMode":"external"' "external query-surface mode"
  assert_contains "$query_contract" '"bundledQueryUiAvailable":false' "external query-ui availability"
fi
assert_worker_startup_check

if [ "${CORTEX_AUTH_MODE:-fixture}" = "fixture" ]; then
  curl \
    --silent \
    --show-error \
    --fail \
    -H "Host: ${CORTEX_QUERY_HOST}" \
    -H "Authorization: Bearer fixture-admin" \
    -X POST "http://127.0.0.1:${CORTEX_EDGE_PORT}/v1/dev/seed" >/dev/null

  chat_response="$(curl \
    --silent \
    --show-error \
    --fail \
    -D - \
    -H "Host: ${CORTEX_QUERY_HOST}" \
    -H "Authorization: Bearer fixture-employee" \
    -H "Content-Type: application/json" \
    -X POST "http://127.0.0.1:${CORTEX_EDGE_PORT}/v1/chat/completions" \
    -d '{"model":"cortex-bounded-rag","messages":[{"role":"user","content":"What are our retentin rules?"}],"stream":false,"cortex":{"showCitations":true}}')"
  assert_contains "$chat_response" 'x-cortex-contract-version: v1' "chat response contract version header" # X-Cortex-Contract-Version: v1
  assert_contains "$chat_response" 'x-cortex-trace-id:' "chat response trace header" # X-Cortex-Trace-Id
  assert_contains "$chat_response" 'x-cortex-evidence-status:' "chat response evidence-status header" # X-Cortex-Evidence-Status
  assert_contains "$chat_response" 'x-cortex-route:' "chat response route header" # X-Cortex-Route
  assert_contains "$chat_response" 'x-cortex-abstained:' "chat response abstention header" # X-Cortex-Abstained
  assert_contains "$chat_response" '"object":"chat.completion"' "chat response object type"
  assert_contains "$chat_response" '"x_cortex"' "chat response extension payload"
  assert_contains "$chat_response" '"contractVersion":"v1"' "chat response contract version"
  assert_contains "$chat_response" '"traceId"' "chat response trace identifier"
  assert_contains "$chat_response" '"traceEventsPath"' "chat response trace-events path"
fi

echo "Package verification passed for ${CORTEX_CONSOLE_HOST} and ${CORTEX_QUERY_HOST}."

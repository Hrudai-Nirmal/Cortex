#!/usr/bin/env bash
# Print split-host package health so operators can inspect a running deployment quickly.

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

read_json() {
  local host="$1"
  local path="$2"
  curl --silent --show-error --fail -H "Host: ${host}" "http://127.0.0.1:${CORTEX_EDGE_PORT}${path}"
}

try_read_json() {
  local host="$1"
  local path="$2"
  curl --silent --show-error --fail -H "Host: ${host}" "http://127.0.0.1:${CORTEX_EDGE_PORT}${path}" 2>/tmp/cortex-package-status-error.$$ || return 1
}

read_headers() {
  local host="$1"
  local path="$2"
  curl --silent --show-error --fail -D - -o /dev/null -H "Host: ${host}" "http://127.0.0.1:${CORTEX_EDGE_PORT}${path}" | tr -d '\r'
}

read_status_code() {
  local host="$1"
  local path="$2"
  curl --silent --show-error -o /dev/null -w "%{http_code}" -H "Host: ${host}" "http://127.0.0.1:${CORTEX_EDGE_PORT}${path}"
}

read_text() {
  local host="$1"
  local path="$2"
  curl --silent --show-error --fail -H "Host: ${host}" "http://127.0.0.1:${CORTEX_EDGE_PORT}${path}"
}

print_surface_identity() {
  local host="$1"
  local headers="$2"
  local surface_line=""

  surface_line="$(printf "%s\n" "$headers" | grep -i '^X-Cortex-Surface:' | tail -n 1 | tr -d '\r')"
  if [ -n "$surface_line" ]; then
    echo "  ${host} -> ${surface_line#X-Cortex-Surface: }"
  else
    echo "  ${host} -> unknown"
  fi
}

print_health() {
  local label="$1"
  local payload="$2"
  if command -v python3 >/dev/null 2>&1; then
    HEALTH_LABEL="$label" HEALTH_PAYLOAD="$payload" python3 - <<'PY'
import json
import os

label = os.environ["HEALTH_LABEL"]
payload = json.loads(os.environ["HEALTH_PAYLOAD"])
print(f"{label}: {payload.get('status', 'unknown')} ({payload.get('environment', 'unknown')})")
for component in payload.get("components", []):
    severity = component.get("severity", "info")
    remediation = component.get("remediation")
    print(f"  - {component['name']}: {component['status']} [{severity}] :: {component['detail']}")
    if remediation:
        print(f"      remediation: {remediation}")
PY
  else
    printf "%s: %s\n" "$label" "$payload"
  fi
}

print_deployment_contract_summary() {
  local payload="$1"
  if command -v python3 >/dev/null 2>&1; then
    DEPLOYMENT_CONTRACT_PAYLOAD="$payload" python3 - <<'PY'
import json
import os
import re

payload = json.loads(os.environ["DEPLOYMENT_CONTRACT_PAYLOAD"])
detail = ""
for component in payload.get("components", []):
    if component.get("name") == "deployment-config":
        detail = component.get("detail", "")
        break

console_match = re.search(r"console=([^,]+), query=", detail)
query_match = re.search(r"query=([^,]+), cors=", detail)
startup_policy_match = re.search(r"startupPolicy=([^,]+)", detail)
surface_mode_match = re.search(r"querySurfaceMode=(bundled|external)", detail)

print("deployment contract:")
print(f"  - console: {console_match.group(1) if console_match else 'missing'}")
print(f"  - query: {query_match.group(1) if query_match else 'missing'}")
print(
    "  - startup policy: "
    f"{startup_policy_match.group(1) if startup_policy_match else 'missing'}"
)
print(
    "  - query surface mode: "
    f"{surface_mode_match.group(1) if surface_mode_match else 'missing'}"
)
PY
  else
    printf "deployment contract: %s\n" "$payload"
  fi
}

print_contract_summary() {
  local payload="$1"
  if [ -z "$payload" ]; then
    echo "query contract: unavailable"
    return 0
  fi
  if command -v python3 >/dev/null 2>&1; then
    CONTRACT_PAYLOAD="$payload" python3 - <<'PY'
import json
import os

payload = json.loads(os.environ["CONTRACT_PAYLOAD"])
print("query contract:")
print(
    f"  - v{payload.get('contractVersion')} :: "
    f"{payload.get('method')} {payload.get('endpointPath')} :: "
    f"auth={payload.get('authentication')} :: "
    f"streaming={payload.get('supportsStreaming')}"
)
print(
    "  - surface mode: "
    f"{payload.get('querySurfaceMode')} :: "
    f"bundledQueryUiAvailable={payload.get('bundledQueryUiAvailable')}"
)
print(f"  - trace events: {payload.get('traceEventsPathTemplate')}")
print(f"  - routes: {', '.join(payload.get('routes', []))}")
print(f"  - abstention evidence: {', '.join(payload.get('abstentionEvidenceStatuses', []))}")
print(f"  - response headers: {', '.join(payload.get('responseHeaders', []))}")
requestOptions = payload.get("requestOptions", {})
print(
    "  - request semantics: "
    f"userMessageSelectionPolicy={requestOptions.get('userMessageSelectionPolicy')} :: "
    f"streamRequiredValue={requestOptions.get('streamRequiredValue')} :: "
    f"supportsCitationToggle={requestOptions.get('supportsCitationToggle')}"
)
print(
    "  - employee-safe fields: "
    f"{', '.join(payload.get('employeeSafeExtensionFields', []))}"
)
print(
    "  - operator-only fields: "
    f"{', '.join(payload.get('operatorOnlyExtensionFields', []))}"
)
errorStatuses = payload.get("errorStatuses", [])
errorStatusSummary = ", ".join(
    f"{errorStatus.get('statusCode')}:{errorStatus.get('code')}:{errorStatus.get('retryable')}"
    for errorStatus in errorStatuses
)
print(f"  - error statuses: {errorStatusSummary}")
PY
  else
    printf "query contract: %s\n" "$payload"
  fi
}

print_contract_fetch_error() {
  local error_detail="$1"
  if [ -n "$error_detail" ]; then
    echo "query contract detail: ${error_detail}"
  fi
}

print_schema_summary() {
  local label="$1"
  local payload="$2"
  if [ -z "$payload" ]; then
    if [ "$label" = "query request schema" ]; then
      echo "query request schema: unavailable"
      return 0
    fi
    if [ "$label" = "query response schema" ]; then
      echo "query response schema: unavailable"
      return 0
    fi
    echo "${label}: unavailable"
    return 0
  fi
  if command -v python3 >/dev/null 2>&1; then
    SCHEMA_LABEL="$label" SCHEMA_PAYLOAD="$payload" python3 - <<'PY'
import json
import os

label = os.environ["SCHEMA_LABEL"]
payload = json.loads(os.environ["SCHEMA_PAYLOAD"])
properties = payload.get("properties", {})
property_names = ", ".join(properties.keys())
print(f"{label}:")
print(f"  - schema title: {payload.get('title', 'missing')}")
print(f"  - top-level properties: {property_names or 'missing'}")
PY
  else
    printf "%s: %s\n" "$label" "$payload"
  fi
}

print_runtime_config_summary() {
  local label="$1"
  local payload="$2"
  if command -v python3 >/dev/null 2>&1; then
    RUNTIME_CONFIG_LABEL="$label" RUNTIME_CONFIG_PAYLOAD="$payload" python3 - <<'PY'
import os
import re

label = os.environ["RUNTIME_CONFIG_LABEL"]
payload = os.environ["RUNTIME_CONFIG_PAYLOAD"]

console_match = re.search(r'consolePublicUrl: "([^"]+)"', payload)
query_match = re.search(r'queryPublicUrl: "([^"]+)"', payload)
print(f"{label} runtime config:")
print(f"  - console: {console_match.group(1) if console_match else 'missing'}")
print(f"  - query: {query_match.group(1) if query_match else 'missing'}")
PY
  else
    printf "%s runtime config: %s\n" "$label" "$payload"
  fi
}

print_cache_header_summary() {
  local label="$1"
  local headers="$2"
  local cache_control_line=""

  cache_control_line="$(printf "%s\n" "$headers" | grep -i '^Cache-Control:' | tail -n 1 | tr -d '\r')"
  if [ -n "$cache_control_line" ]; then
    echo "${label} runtime-config cache: ${cache_control_line#Cache-Control: }"
  else
    echo "${label} runtime-config cache: missing"
  fi
}

print_worker_status() {
  if docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" exec -T worker \
    python -m cortex.worker --check-startup >/dev/null 2>&1; then
    echo "worker startup: ready"
  else
    echo "worker startup: blocked"
    docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" logs --tail=20 worker 2>/dev/null || true
  fi
}

print_worker_contract_summary() {
  local payload="$1"
  if command -v python3 >/dev/null 2>&1; then
    WORKER_STARTUP_PAYLOAD="$payload" python3 - <<'PY'
import json
import os

payload = json.loads(os.environ["WORKER_STARTUP_PAYLOAD"])
print("worker startup contract:")
print(f"  - status: {payload.get('status', 'unknown')}")
print(f"  - startup status: {payload.get('startupStatus', 'unknown')}")
print(f"  - live readiness status: {payload.get('liveReadinessStatus', 'unknown')}")
print(f"  - blocking phase: {payload.get('blockingPhase', 'unknown')}")
print(f"  - detail: {payload.get('detail', 'missing')}")
for component in payload.get("failingComponents", []):
    remediation = component.get("remediation")
    print(
        f"  - blocker {component.get('name', 'unknown')}: "
        f"{component.get('status', 'unknown')} [{component.get('severity', 'info')}] :: "
        f"{component.get('detail', 'missing')}"
    )
    if remediation:
        print(f"      remediation: {remediation}")
PY
  else
    printf "worker startup contract: %s\n" "$payload"
  fi
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

CORTEX_QUERY_SURFACE_MODE="${CORTEX_QUERY_SURFACE_MODE:-bundled}"

if [ "$CORTEX_QUERY_SURFACE_MODE" = "external" ]; then
  COMPOSE_FILE="$EXTERNAL_QUERY_COMPOSE_FILE"
fi

startup_payload="$(read_json "$CORTEX_CONSOLE_HOST" "/health/startup")"
ready_payload="$(read_json "$CORTEX_CONSOLE_HOST" "/health/ready")"
query_startup_payload="$(read_json "$CORTEX_QUERY_HOST" "/health/startup")"
query_ready_payload="$(read_json "$CORTEX_QUERY_HOST" "/health/ready")"
worker_startup_payload="$(read_json "$CORTEX_QUERY_HOST" "/health/worker-startup")"
query_contract_payload=""
query_contract_error=""
query_request_schema_payload=""
query_response_schema_payload=""
if query_contract_payload="$(try_read_json "$CORTEX_QUERY_HOST" "/v1/chat/contracts/v1")"; then
  :
else
  query_contract_error="$(cat /tmp/cortex-package-status-error.$$ 2>/dev/null || true)"
fi
if query_request_schema_payload="$(try_read_json "$CORTEX_QUERY_HOST" "/v1/chat/contracts/v1/schemas/request")"; then
  :
fi
if query_response_schema_payload="$(try_read_json "$CORTEX_QUERY_HOST" "/v1/chat/contracts/v1/schemas/response")"; then
  :
fi
rm -f /tmp/cortex-package-status-error.$$ 2>/dev/null || true
console_runtime_config="$(read_text "$CORTEX_CONSOLE_HOST" "/cortex-runtime-config.js")"
console_runtime_config_headers="$(read_headers "$CORTEX_CONSOLE_HOST" "/cortex-runtime-config.js")"
console_headers="$(read_headers "$CORTEX_CONSOLE_HOST" "/")"

echo "Console host: ${CORTEX_CONSOLE_HOST}"
echo "Query host:   ${CORTEX_QUERY_HOST}"
echo "Edge port:    ${CORTEX_EDGE_PORT}"
echo "Query surface mode: ${CORTEX_QUERY_SURFACE_MODE}"
echo "Surface routing:"
print_surface_identity "$CORTEX_CONSOLE_HOST" "$console_headers"
if [ "$CORTEX_QUERY_SURFACE_MODE" = "bundled" ]; then
  query_runtime_config="$(read_text "$CORTEX_QUERY_HOST" "/cortex-runtime-config.js")"
  query_runtime_config_headers="$(read_headers "$CORTEX_QUERY_HOST" "/cortex-runtime-config.js")"
  query_headers="$(read_headers "$CORTEX_QUERY_HOST" "/")"
  print_surface_identity "$CORTEX_QUERY_HOST" "$query_headers"
else
  query_root_status="$(read_status_code "$CORTEX_QUERY_HOST" "/")"
  echo "  ${CORTEX_QUERY_HOST} -> external-query-ui (not bundled)"
  echo "  query host root status: ${query_root_status} (expected 404 for API-only mode)"
fi
print_health "console startup" "$startup_payload"
print_health "console ready" "$ready_payload"
print_health "query startup" "$query_startup_payload"
print_health "query ready" "$query_ready_payload"
print_deployment_contract_summary "$startup_payload"
print_runtime_config_summary "console" "$console_runtime_config"
print_cache_header_summary "console" "$console_runtime_config_headers"
if [ "$CORTEX_QUERY_SURFACE_MODE" = "bundled" ]; then
  print_runtime_config_summary "query" "$query_runtime_config"
  print_cache_header_summary "query" "$query_runtime_config_headers"
fi
print_contract_summary "$query_contract_payload"
print_contract_fetch_error "$query_contract_error"
print_schema_summary "query request schema" "$query_request_schema_payload"
print_schema_summary "query response schema" "$query_response_schema_payload"
print_worker_contract_summary "$worker_startup_payload"
print_worker_status

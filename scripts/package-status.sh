#!/usr/bin/env bash
# Print split-host package health so operators can inspect a running deployment quickly.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="${1:-$ROOT_DIR/.env.package}"
COMPOSE_FILE="$ROOT_DIR/docker-compose.package.yml"

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}

read_json() {
  local host="$1"
  local path="$2"
  curl --silent --show-error --fail -H "Host: ${host}" "http://127.0.0.1:${CORTEX_EDGE_PORT}${path}"
}

read_headers() {
  local host="$1"
  local path="$2"
  curl --silent --show-error --fail -D - -o /dev/null -H "Host: ${host}" "http://127.0.0.1:${CORTEX_EDGE_PORT}${path}" | tr -d '\r'
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

print_contract_summary() {
  local payload="$1"
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
print(f"  - trace events: {payload.get('traceEventsPathTemplate')}")
print(f"  - routes: {', '.join(payload.get('routes', []))}")
print(f"  - abstention evidence: {', '.join(payload.get('abstentionEvidenceStatuses', []))}")
print(f"  - response headers: {', '.join(payload.get('responseHeaders', []))}")
PY
  else
    printf "query contract: %s\n" "$payload"
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

require_command curl
require_command docker

if [ ! -f "$ENV_FILE" ]; then
  echo "Package env file not found: $ENV_FILE" >&2
  exit 1
fi

set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a

startup_payload="$(read_json "$CORTEX_CONSOLE_HOST" "/health/startup")"
ready_payload="$(read_json "$CORTEX_CONSOLE_HOST" "/health/ready")"
query_startup_payload="$(read_json "$CORTEX_QUERY_HOST" "/health/startup")"
query_ready_payload="$(read_json "$CORTEX_QUERY_HOST" "/health/ready")"
query_contract_payload="$(read_json "$CORTEX_QUERY_HOST" "/v1/chat/contracts/v1")"
console_runtime_config="$(read_text "$CORTEX_CONSOLE_HOST" "/cortex-runtime-config.js")"
query_runtime_config="$(read_text "$CORTEX_QUERY_HOST" "/cortex-runtime-config.js")"
console_runtime_config_headers="$(read_headers "$CORTEX_CONSOLE_HOST" "/cortex-runtime-config.js")"
query_runtime_config_headers="$(read_headers "$CORTEX_QUERY_HOST" "/cortex-runtime-config.js")"
console_headers="$(read_headers "$CORTEX_CONSOLE_HOST" "/")"
query_headers="$(read_headers "$CORTEX_QUERY_HOST" "/")"

echo "Console host: ${CORTEX_CONSOLE_HOST}"
echo "Query host:   ${CORTEX_QUERY_HOST}"
echo "Edge port:    ${CORTEX_EDGE_PORT}"
echo "Surface routing:"
print_surface_identity "$CORTEX_CONSOLE_HOST" "$console_headers"
print_surface_identity "$CORTEX_QUERY_HOST" "$query_headers"
print_health "console startup" "$startup_payload"
print_health "console ready" "$ready_payload"
print_health "query startup" "$query_startup_payload"
print_health "query ready" "$query_ready_payload"
print_runtime_config_summary "console" "$console_runtime_config"
print_runtime_config_summary "query" "$query_runtime_config"
print_cache_header_summary "console" "$console_runtime_config_headers"
print_cache_header_summary "query" "$query_runtime_config_headers"
print_contract_summary "$query_contract_payload"
print_worker_status

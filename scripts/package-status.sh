#!/usr/bin/env bash
# Print split-host package health so operators can inspect a running deployment quickly.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="${1:-$ROOT_DIR/.env.package}"

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

require_command curl

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

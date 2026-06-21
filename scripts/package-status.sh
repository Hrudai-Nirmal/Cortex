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

echo "Console host: ${CORTEX_CONSOLE_HOST}"
echo "Query host:   ${CORTEX_QUERY_HOST}"
echo "Edge port:    ${CORTEX_EDGE_PORT}"
print_health "startup" "$startup_payload"
print_health "ready" "$ready_payload"

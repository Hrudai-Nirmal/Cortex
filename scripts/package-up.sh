#!/usr/bin/env bash
# Validate operator configuration, start the shippable package, and wait for health.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
COMPOSE_FILE="$ROOT_DIR/docker-compose.package.yml"
ENV_FILE="${1:-$ROOT_DIR/.env.package}"

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}

extract_url_host() {
  printf "%s" "$1" | sed -E 's#^[a-zA-Z]+://([^/:]+).*#\1#'
}

require_env() {
  local name="$1"
  if [ -z "${!name:-}" ]; then
    echo "Missing required environment value: $name" >&2
    exit 1
  fi
}

wait_for_endpoint() {
  local host="$1"
  local path="$2"
  local expected_text="$3"
  local max_attempts="${4:-30}"
  local target_url="http://127.0.0.1:${CORTEX_EDGE_PORT}${path}"

  for _ in $(seq 1 "$max_attempts"); do
    if response="$(curl --silent --show-error --fail -H "Host: ${host}" "$target_url" 2>/dev/null)"; then
      if printf "%s" "$response" | grep -q "$expected_text"; then
        return 0
      fi
    fi
    sleep 2
  done

  echo "Timed out waiting for ${host}${path}" >&2
  exit 1
}

read_headers() {
  local host="$1"
  local path="$2"
  curl --silent --show-error --fail -D - -o /dev/null -H "Host: ${host}" "http://127.0.0.1:${CORTEX_EDGE_PORT}${path}"
}

assert_surface_header() {
  local host="$1"
  local expected_surface="$2"
  local headers=""

  headers="$(read_headers "$host" "/")"
  if ! printf "%s" "$headers" | grep -qi "^X-Cortex-Surface: ${expected_surface}$"; then
    echo "Expected ${host} to resolve to Cortex surface ${expected_surface}, but the routed headers did not match." >&2
    printf "%s\n" "$headers" >&2
    exit 1
  fi
}

get_json() {
  local host="$1"
  local path="$2"
  curl --silent --show-error --fail -H "Host: ${host}" "http://127.0.0.1:${CORTEX_EDGE_PORT}${path}"
}

wait_for_health_ready() {
  local host="$1"
  local path="$2"
  local label="$3"
  local max_attempts="${4:-30}"
  local payload=""

  for _ in $(seq 1 "$max_attempts"); do
    payload="$(get_json "$host" "$path" || true)"
    if printf "%s" "$payload" | grep -q '"status":"ready"'; then
      return 0
    fi
    if printf "%s" "$payload" | grep -q '"status":"degraded"'; then
      echo "Package ${label} failed." >&2
      print_health_failures "$payload" >&2
      exit 1
    fi
    sleep 2
  done

  echo "Timed out waiting for ${label} on ${host}${path}" >&2
  if [ -n "$payload" ]; then
    print_health_failures "$payload" >&2
  fi
  exit 1
}

print_health_failures() {
  local payload="$1"
  if command -v python3 >/dev/null 2>&1; then
    HEALTH_PAYLOAD="$payload" python3 - <<'PY'
import json
import os

payload = json.loads(os.environ["HEALTH_PAYLOAD"])
for component in payload.get("components", []):
    if component.get("status") == "ready":
        continue
    print(f"- {component['name']}: {component['status']} [{component.get('severity', 'info')}] :: {component['detail']}")
    remediation = component.get("remediation")
    if remediation:
        print(f"  remediation: {remediation}")
PY
  else
    printf "%s\n" "$payload"
  fi
}

require_command docker
require_command curl

if [ ! -f "$ENV_FILE" ]; then
  echo "Package env file not found: $ENV_FILE" >&2
  echo "Copy .env.package.example to .env.package and set your client domains first." >&2
  exit 1
fi

set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a

require_env CORTEX_CONSOLE_HOST
require_env CORTEX_QUERY_HOST
require_env CORTEX_CONSOLE_PUBLIC_URL
require_env CORTEX_QUERY_PUBLIC_URL
require_env CORTEX_DATABASE_URL
require_env CORTEX_OBJECT_STORAGE_ROOT
require_env CORTEX_OLLAMA_BASE_URL
require_env CORTEX_EDGE_PORT

if [ "$CORTEX_CONSOLE_HOST" = "$CORTEX_QUERY_HOST" ]; then
  echo "CORTEX_CONSOLE_HOST and CORTEX_QUERY_HOST must be different." >&2
  exit 1
fi

if [ "$(extract_url_host "$CORTEX_CONSOLE_PUBLIC_URL")" != "$CORTEX_CONSOLE_HOST" ]; then
  echo "CORTEX_CONSOLE_PUBLIC_URL must match CORTEX_CONSOLE_HOST." >&2
  exit 1
fi

if [ "$(extract_url_host "$CORTEX_QUERY_PUBLIC_URL")" != "$CORTEX_QUERY_HOST" ]; then
  echo "CORTEX_QUERY_PUBLIC_URL must match CORTEX_QUERY_HOST." >&2
  exit 1
fi

docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" config >/dev/null
docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" up -d --build

wait_for_health_ready "$CORTEX_CONSOLE_HOST" "/health/startup" "startup validation"
wait_for_health_ready "$CORTEX_QUERY_HOST" "/health/startup" "query-host startup validation"
wait_for_endpoint "$CORTEX_CONSOLE_HOST" "/" "<!doctype html" 40
wait_for_endpoint "$CORTEX_QUERY_HOST" "/" "<!doctype html" 40
assert_surface_header "$CORTEX_CONSOLE_HOST" "console"
assert_surface_header "$CORTEX_QUERY_HOST" "query"

wait_for_health_ready "$CORTEX_CONSOLE_HOST" "/health/ready" "runtime readiness"
wait_for_health_ready "$CORTEX_QUERY_HOST" "/health/ready" "query-host runtime readiness"

echo "Package is up."
echo "Console URL: ${CORTEX_CONSOLE_PUBLIC_URL}"
echo "Query URL:   ${CORTEX_QUERY_PUBLIC_URL}"
echo "Local edge:  http://127.0.0.1:${CORTEX_EDGE_PORT}"

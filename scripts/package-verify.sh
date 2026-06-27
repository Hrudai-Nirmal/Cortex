#!/usr/bin/env bash
# Verify split-host routing, health probes, and the external query contract on a running package.

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

if [ ! -f "$ENV_FILE" ]; then
  echo "Package env file not found: $ENV_FILE" >&2
  exit 1
fi

set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a

console_html="$(curl --silent --show-error --fail -H "Host: ${CORTEX_CONSOLE_HOST}" "http://127.0.0.1:${CORTEX_EDGE_PORT}/")"
query_html="$(curl --silent --show-error --fail -H "Host: ${CORTEX_QUERY_HOST}" "http://127.0.0.1:${CORTEX_EDGE_PORT}/")"
console_headers="$(curl --silent --show-error --fail -D - -o /dev/null -H "Host: ${CORTEX_CONSOLE_HOST}" "http://127.0.0.1:${CORTEX_EDGE_PORT}/" | tr -d '\r')"
query_headers="$(curl --silent --show-error --fail -D - -o /dev/null -H "Host: ${CORTEX_QUERY_HOST}" "http://127.0.0.1:${CORTEX_EDGE_PORT}/" | tr -d '\r')"
console_runtime_config_headers="$(read_headers "$CORTEX_CONSOLE_HOST" "/cortex-runtime-config.js")"
query_runtime_config_headers="$(read_headers "$CORTEX_QUERY_HOST" "/cortex-runtime-config.js")"

printf "%s" "$console_html" | grep -qi "<!doctype html"
printf "%s" "$query_html" | grep -qi "<!doctype html"
printf "%s" "$console_headers" | grep -qi '^X-Cortex-Surface: console'
printf "%s" "$query_headers" | grep -qi '^X-Cortex-Surface: query'
printf "%s" "$console_runtime_config_headers" | grep -qi '^Cache-Control: no-store, no-cache, must-revalidate'
printf "%s" "$query_runtime_config_headers" | grep -qi '^Cache-Control: no-store, no-cache, must-revalidate'
console_runtime_config="$(read_text "$CORTEX_CONSOLE_HOST" "/cortex-runtime-config.js")"
query_runtime_config="$(read_text "$CORTEX_QUERY_HOST" "/cortex-runtime-config.js")"
printf "%s" "$console_runtime_config" | grep -q "consolePublicUrl: \"${CORTEX_CONSOLE_PUBLIC_URL}\""
printf "%s" "$console_runtime_config" | grep -q "queryPublicUrl: \"${CORTEX_QUERY_PUBLIC_URL}\""
printf "%s" "$query_runtime_config" | grep -q "consolePublicUrl: \"${CORTEX_CONSOLE_PUBLIC_URL}\""
printf "%s" "$query_runtime_config" | grep -q "queryPublicUrl: \"${CORTEX_QUERY_PUBLIC_URL}\""

read_json "$CORTEX_CONSOLE_HOST" "/health/live" | grep -q '"status"'
read_json "$CORTEX_QUERY_HOST" "/health/live" | grep -q '"status"'
read_json "$CORTEX_CONSOLE_HOST" "/health/startup" | grep -q '"components"'
read_json "$CORTEX_QUERY_HOST" "/health/startup" | grep -q '"components"'
read_json "$CORTEX_CONSOLE_HOST" "/health/ready" | grep -q '"status":"ready"'
read_json "$CORTEX_QUERY_HOST" "/health/ready" | grep -q '"status":"ready"'
query_contract="$(read_json "$CORTEX_QUERY_HOST" "/v1/chat/contracts/v1")"
printf "%s" "$query_contract" | grep -q '"contractVersion":"v1"'
printf "%s" "$query_contract" | grep -q '"endpointPath":"/v1/chat/completions"'
printf "%s" "$query_contract" | grep -q '"authentication":"bearer-token"'
printf "%s" "$query_contract" | grep -q '"traceEventsPathTemplate":"/v1/query/{traceId}/events"'
printf "%s" "$query_contract" | grep -q '"responseHeaders"'
printf "%s" "$query_contract" | grep -q '"extensionFields"'
docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" exec -T worker \
  python -m cortex.worker --check-startup >/dev/null

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
  printf "%s" "$chat_response" | grep -qi '^x-cortex-contract-version: v1' # X-Cortex-Contract-Version: v1
  printf "%s" "$chat_response" | grep -qi '^x-cortex-trace-id:' # X-Cortex-Trace-Id
  printf "%s" "$chat_response" | grep -qi '^x-cortex-evidence-status:' # X-Cortex-Evidence-Status
  printf "%s" "$chat_response" | grep -qi '^x-cortex-route:' # X-Cortex-Route
  printf "%s" "$chat_response" | grep -qi '^x-cortex-abstained:' # X-Cortex-Abstained
  printf "%s" "$chat_response" | grep -q '"object":"chat.completion"'
  printf "%s" "$chat_response" | grep -q '"x_cortex"'
  printf "%s" "$chat_response" | grep -q '"contractVersion":"v1"'
  printf "%s" "$chat_response" | grep -q '"traceId"'
  printf "%s" "$chat_response" | grep -q '"traceEventsPath"'
fi

echo "Package verification passed for ${CORTEX_CONSOLE_HOST} and ${CORTEX_QUERY_HOST}."

#!/usr/bin/env bash
# Verify split-host routing, health probes, and the external query contract on a running package.

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

require_command curl

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

printf "%s" "$console_html" | grep -qi "<!doctype html"
printf "%s" "$query_html" | grep -qi "<!doctype html"

read_json "$CORTEX_CONSOLE_HOST" "/health/live" | grep -q '"status"'
read_json "$CORTEX_CONSOLE_HOST" "/health/startup" | grep -q '"components"'
read_json "$CORTEX_CONSOLE_HOST" "/health/ready" | grep -q '"status":"ready"'
read_json "$CORTEX_QUERY_HOST" "/health/ready" | grep -q '"status":"ready"'

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
    -H "Host: ${CORTEX_QUERY_HOST}" \
    -H "Authorization: Bearer fixture-employee" \
    -H "Content-Type: application/json" \
    -X POST "http://127.0.0.1:${CORTEX_EDGE_PORT}/v1/chat/completions" \
    -d '{"model":"cortex-bounded-rag","messages":[{"role":"user","content":"What are our retentin rules?"}],"stream":false,"cortex":{"showCitations":true}}')"
  printf "%s" "$chat_response" | grep -q '"object":"chat.completion"'
  printf "%s" "$chat_response" | grep -q '"x_cortex"'
  printf "%s" "$chat_response" | grep -q '"traceId"'
fi

echo "Package verification passed for ${CORTEX_CONSOLE_HOST} and ${CORTEX_QUERY_HOST}."

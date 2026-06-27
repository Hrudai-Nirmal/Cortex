#!/usr/bin/env bash
# Validate operator configuration, start the shippable package, and wait for health.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
DEFAULT_COMPOSE_FILE="$ROOT_DIR/docker-compose.package.yml"
EXTERNAL_QUERY_COMPOSE_FILE="$ROOT_DIR/docker-compose.package.external-query.yml"
COMPOSE_FILE="$DEFAULT_COMPOSE_FILE"
ENV_FILE="${1:-$ROOT_DIR/.env.package}"

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

extract_url_host() {
  printf "%s" "$1" | sed -E 's#^[a-zA-Z]+://([^/:]+).*#\1#'
}

is_reserved_placeholder_host() {
  local host="$1"
  case "$host" in
    example.com|example.org|example.net|example.test|*.example.com|*.example.org|*.example.net|*.example.test)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

require_env() {
  local name="$1"
  if [ -z "${!name:-}" ]; then
    echo "Missing required environment value: $name" >&2
    exit 1
  fi
}

require_one_of() {
  local value="$1"
  local label="$2"
  shift 2
  for allowed_value in "$@"; do
    if [ "$value" = "$allowed_value" ]; then
      return 0
    fi
  done
  echo "${label} must be one of: $*" >&2
  exit 1
}

require_https_public_url() {
  local value="$1"
  local label="$2"

  if [[ ! "$value" =~ ^https://[^/?#]+/?$ ]]; then
    echo "${label} must be an https URL rooted at the host with no path, query string, or fragment." >&2
    exit 1
  fi
}

require_absolute_path() {
  local value="$1"
  local label="$2"

  if [[ "$value" != /* ]]; then
    echo "${label} must be an absolute path inside the package runtime." >&2
    exit 1
  fi
}

require_numeric_port() {
  local value="$1"
  local label="$2"

  if [[ ! "$value" =~ ^[0-9]+$ ]] || [ "$value" -lt 1 ] || [ "$value" -gt 65535 ]; then
    echo "${label} must be an integer between 1 and 65535." >&2
    exit 1
  fi
}

validate_model_endpoint_policy() {
  local base_url="$1"
  local allow_remote="$2"
  local host=""

  host="$(extract_url_host "$base_url")"
  if [ -z "$host" ]; then
    echo "CORTEX_OLLAMA_BASE_URL must be an absolute URL." >&2
    exit 1
  fi

  if [ "$allow_remote" = "true" ]; then
    return 0
  fi

  case "$host" in
    localhost|127.*|10.*|192.168.*|ollama|*.local|*.internal)
      return 0
      ;;
    172.1[6-9].*|172.2[0-9].*|172.3[0-1].*)
      return 0
      ;;
  esac

  if [[ "$host" != *.* ]]; then
    return 0
  fi

  echo "CORTEX_OLLAMA_BASE_URL resolves to ${host}, which is not local/private while CORTEX_ALLOW_REMOTE_MODEL_ENDPOINT=false. Point Cortex at a local model endpoint or explicitly allow the remote dependency." >&2
  exit 1
}

validate_torch_build_profile() {
  local accelerator="$1"
  local torch_index_url="$2"

  if [ "$accelerator" = "cpu" ] && [[ "$torch_index_url" != *"/cpu"* ]]; then
    echo "CORTEX_REQUIRED_ACCELERATOR=cpu expects a CPU-oriented CORTEX_PACKAGE_PYTORCH_WHEEL_INDEX_URL so the package build does not pull CUDA-heavy Torch artifacts." >&2
    exit 1
  fi

  if [ "$accelerator" = "cuda" ] && [[ "$torch_index_url" == *"/cpu"* ]]; then
    echo "CORTEX_REQUIRED_ACCELERATOR=cuda cannot use the CPU PyTorch wheel channel. Point CORTEX_PACKAGE_PYTORCH_WHEEL_INDEX_URL at the matching CUDA wheel channel before rebuilding the package images." >&2
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
  print_compose_diagnostics
  exit 1
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

assert_runtime_config() {
  local host="$1"
  local expected_console_url="$2"
  local expected_query_url="$3"
  local runtime_config=""

  runtime_config="$(read_text "$host" "/cortex-runtime-config.js")"
  if ! printf "%s" "$runtime_config" | grep -q "consolePublicUrl: \"${expected_console_url}\""; then
    echo "Expected ${host} runtime config to publish consolePublicUrl=${expected_console_url}." >&2
    printf "%s\n" "$runtime_config" >&2
    exit 1
  fi
  if ! printf "%s" "$runtime_config" | grep -q "queryPublicUrl: \"${expected_query_url}\""; then
    echo "Expected ${host} runtime config to publish queryPublicUrl=${expected_query_url}." >&2
    printf "%s\n" "$runtime_config" >&2
    exit 1
  fi
}

assert_runtime_config_cache_header() {
  local host="$1"
  local headers=""

  headers="$(read_headers "$host" "/cortex-runtime-config.js")"
  if ! printf "%s" "$headers" | grep -qi '^Cache-Control: no-store, no-cache, must-revalidate$'; then
    echo "Expected ${host} runtime config to be served with Cache-Control: no-store, no-cache, must-revalidate." >&2
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
      print_compose_diagnostics
      exit 1
    fi
    sleep 2
  done

  echo "Timed out waiting for ${label} on ${host}${path}" >&2
  if [ -n "$payload" ]; then
    print_health_failures "$payload" >&2
  fi
  print_compose_diagnostics
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

print_compose_diagnostics() {
  echo "Compose service state:" >&2
  docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" ps >&2 || true
  echo "Recent service logs:" >&2
  docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" logs --tail=40 api worker edge >&2 || true
}

wait_for_worker_startup_check() {
  local max_attempts="${1:-20}"

  for _ in $(seq 1 "$max_attempts"); do
    if docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" exec -T worker \
      python -m cortex.worker --check-startup >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
  done

  echo "Timed out waiting for the worker startup check to pass." >&2
  print_compose_diagnostics
  exit 1
}

wait_for_query_contract() {
  wait_for_endpoint "$CORTEX_QUERY_HOST" "/v1/chat/contracts/v1" '"contractVersion":"v1"' 40
}

require_command docker
require_command curl
require_docker_daemon

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
require_env CORTEX_ENVIRONMENT
require_env CORTEX_DEV_MODE
require_env CORTEX_QUERY_SURFACE_MODE
require_env CORTEX_AUTH_MODE
require_env CORTEX_DATABASE_URL
require_env CORTEX_OBJECT_STORAGE_ROOT
require_env CORTEX_OLLAMA_BASE_URL
require_env CORTEX_ALLOW_REMOTE_MODEL_ENDPOINT
require_env CORTEX_GENERATOR_MODEL
require_env CORTEX_EMBEDDING_MODEL
require_env CORTEX_REQUIRED_ACCELERATOR
require_env CORTEX_PACKAGE_PYTORCH_WHEEL_INDEX_URL
require_env CORTEX_EDGE_PORT

require_one_of "$CORTEX_ENVIRONMENT" "CORTEX_ENVIRONMENT" production
require_one_of "$CORTEX_DEV_MODE" "CORTEX_DEV_MODE" false
require_one_of "$CORTEX_QUERY_SURFACE_MODE" "CORTEX_QUERY_SURFACE_MODE" bundled external
require_one_of "$CORTEX_ALLOW_REMOTE_MODEL_ENDPOINT" "CORTEX_ALLOW_REMOTE_MODEL_ENDPOINT" true false
require_one_of "$CORTEX_REQUIRED_ACCELERATOR" "CORTEX_REQUIRED_ACCELERATOR" cpu mps cuda
validate_torch_build_profile "$CORTEX_REQUIRED_ACCELERATOR" "$CORTEX_PACKAGE_PYTORCH_WHEEL_INDEX_URL"
require_numeric_port "$CORTEX_EDGE_PORT" "CORTEX_EDGE_PORT"
require_absolute_path "$CORTEX_OBJECT_STORAGE_ROOT" "CORTEX_OBJECT_STORAGE_ROOT"
require_https_public_url "$CORTEX_CONSOLE_PUBLIC_URL" "CORTEX_CONSOLE_PUBLIC_URL"
require_https_public_url "$CORTEX_QUERY_PUBLIC_URL" "CORTEX_QUERY_PUBLIC_URL"
validate_model_endpoint_policy "$CORTEX_OLLAMA_BASE_URL" "$CORTEX_ALLOW_REMOTE_MODEL_ENDPOINT"

if [ "$CORTEX_CONSOLE_HOST" = "$CORTEX_QUERY_HOST" ]; then
  echo "CORTEX_CONSOLE_HOST and CORTEX_QUERY_HOST must be different." >&2
  exit 1
fi

if is_reserved_placeholder_host "$CORTEX_CONSOLE_HOST" || is_reserved_placeholder_host "$CORTEX_QUERY_HOST"; then
  echo "CORTEX_CONSOLE_HOST and CORTEX_QUERY_HOST must be replaced with the client's real domains before booting the package." >&2
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

if [ "$CORTEX_QUERY_SURFACE_MODE" = "external" ]; then
  COMPOSE_FILE="$EXTERNAL_QUERY_COMPOSE_FILE"
fi

docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" config >/dev/null
echo "Package PyTorch wheel source: ${CORTEX_PACKAGE_PYTORCH_WHEEL_INDEX_URL}"
echo "Query surface mode: ${CORTEX_QUERY_SURFACE_MODE}"
docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" up -d --build

wait_for_health_ready "$CORTEX_CONSOLE_HOST" "/health/startup" "startup validation"
wait_for_endpoint "$CORTEX_CONSOLE_HOST" "/" "<!doctype html" 40
assert_surface_header "$CORTEX_CONSOLE_HOST" "console"
assert_runtime_config "$CORTEX_CONSOLE_HOST" "$CORTEX_CONSOLE_PUBLIC_URL" "$CORTEX_QUERY_PUBLIC_URL"
assert_runtime_config_cache_header "$CORTEX_CONSOLE_HOST"

wait_for_health_ready "$CORTEX_CONSOLE_HOST" "/health/ready" "runtime readiness"
if [ "$CORTEX_QUERY_SURFACE_MODE" = "bundled" ]; then
  wait_for_health_ready "$CORTEX_QUERY_HOST" "/health/startup" "query-host startup validation"
  wait_for_endpoint "$CORTEX_QUERY_HOST" "/" "<!doctype html" 40
  assert_surface_header "$CORTEX_QUERY_HOST" "query"
  assert_runtime_config "$CORTEX_QUERY_HOST" "$CORTEX_CONSOLE_PUBLIC_URL" "$CORTEX_QUERY_PUBLIC_URL"
  assert_runtime_config_cache_header "$CORTEX_QUERY_HOST"
  wait_for_health_ready "$CORTEX_QUERY_HOST" "/health/ready" "query-host runtime readiness"
else
  wait_for_health_ready "$CORTEX_QUERY_HOST" "/health/startup" "query-host api startup validation"
  wait_for_health_ready "$CORTEX_QUERY_HOST" "/health/ready" "query-host api runtime readiness"
fi
wait_for_query_contract
wait_for_worker_startup_check

echo "Package is up."
echo "Console URL: ${CORTEX_CONSOLE_PUBLIC_URL}"
echo "Query URL:   ${CORTEX_QUERY_PUBLIC_URL}"
echo "Local edge:  http://127.0.0.1:${CORTEX_EDGE_PORT}"

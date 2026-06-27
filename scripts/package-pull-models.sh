#!/usr/bin/env bash
# Pull the configured generator and embedding models into the running Ollama package service.

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

require_docker_daemon() {
  if docker info >/dev/null 2>&1; then
    return 0
  fi
  echo "Docker is installed but the daemon is not reachable." >&2
  echo "Start Docker Desktop or the target container runtime before running package commands." >&2
  exit 1
}

require_env() {
  local name="$1"
  if [ -z "${!name:-}" ]; then
    echo "Missing required environment value: $name" >&2
    exit 1
  fi
}

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

require_env CORTEX_GENERATOR_MODEL
require_env CORTEX_EMBEDDING_MODEL
require_env CORTEX_ALLOW_REMOTE_MODEL_ENDPOINT
require_env CORTEX_OLLAMA_BASE_URL

if [ "$CORTEX_ALLOW_REMOTE_MODEL_ENDPOINT" = "true" ]; then
  echo "package:pull-models only manages the bundled local Ollama service." >&2
  echo "Disable CORTEX_ALLOW_REMOTE_MODEL_ENDPOINT or pull the required models into the remote provider directly." >&2
  echo "Configured model endpoint: ${CORTEX_OLLAMA_BASE_URL}" >&2
  exit 1
fi

docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" exec -T ollama \
  ollama pull "$CORTEX_GENERATOR_MODEL"
docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" exec -T ollama \
  ollama pull "$CORTEX_EMBEDDING_MODEL"

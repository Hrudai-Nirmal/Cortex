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

require_env() {
  local name="$1"
  if [ -z "${!name:-}" ]; then
    echo "Missing required environment value: $name" >&2
    exit 1
  fi
}

require_command docker

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

docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" exec -T ollama \
  ollama pull "$CORTEX_GENERATOR_MODEL"
docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" exec -T ollama \
  ollama pull "$CORTEX_EMBEDDING_MODEL"

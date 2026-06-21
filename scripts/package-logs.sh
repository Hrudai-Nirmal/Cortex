#!/usr/bin/env bash
# Tail package service logs through the shared compose file and env configuration.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
COMPOSE_FILE="$ROOT_DIR/docker-compose.package.yml"
ENV_FILE="${1:-$ROOT_DIR/.env.package}"
SERVICE_NAME="${2:-}"

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}

require_command docker

if [ ! -f "$ENV_FILE" ]; then
  echo "Package env file not found: $ENV_FILE" >&2
  exit 1
fi

if [ -n "$SERVICE_NAME" ]; then
  docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" logs --tail 200 -f "$SERVICE_NAME"
else
  docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" logs --tail 200 -f
fi

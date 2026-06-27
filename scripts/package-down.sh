#!/usr/bin/env bash
# Stop the shippable package while preserving volumes unless --volumes is supplied.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
COMPOSE_FILE="$ROOT_DIR/docker-compose.package.yml"
ENV_FILE="${1:-$ROOT_DIR/.env.package}"
REMOVE_VOLUMES="${2:-}"

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

require_command docker
require_docker_daemon

if [ ! -f "$ENV_FILE" ]; then
  echo "Package env file not found: $ENV_FILE" >&2
  exit 1
fi

if [ "$REMOVE_VOLUMES" = "--volumes" ] || [ "$ENV_FILE" = "--volumes" ]; then
  if [ "$ENV_FILE" = "--volumes" ]; then
    ENV_FILE="$ROOT_DIR/.env.package"
  fi
  docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" down -v
else
  docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" down
fi

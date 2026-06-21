#!/usr/bin/env bash
# Stop local Cortex processes and clear the live-integration development state.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
RUN_DIR="$ROOT_DIR/.cortex-data/run"

stop_process() {
  local name="$1"
  local pid_file="$RUN_DIR/$name.pid"
  if [ -f "$pid_file" ]; then
    local pid
    pid="$(cat "$pid_file")"
    if kill -0 "$pid" >/dev/null 2>&1; then
      kill "$pid"
    fi
    rm -f "$pid_file"
  fi
}

cd "$ROOT_DIR"
stop_process api
stop_process worker
stop_process console-web
stop_process query-web

docker compose down -v || true
rm -rf "$ROOT_DIR/.cortex-data/object-storage" "$RUN_DIR"
